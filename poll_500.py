"""Lightweight 500.com HTML odds polling (no xls download)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from download_500 import BASE, MatchFixture, _serialize_xls_table, fetch_live_fixtures
from http_client import ScraperGuard, get_text, make_session
from betfair_500 import fetch_betfair_snapshot
from eu_odds_chart import eu_books_fingerprint, parse_eu_bookmakers, select_major_eu_books
from jingcai_500 import build_jingcai_snapshot, fetch_jczq_meta_by_order, fetch_live_odds_list
from parser import parse_handicap

log = logging.getLogger(__name__)


def _to_float(text: str) -> float | None:
    text = str(text or "").strip().replace("↑", "").replace("↓", "")
    if not text or text in {"-", "—"}:
        return None
    # 百分比列（36.58%）不是赔率
    if text.endswith("%"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_plausible_eu_odds(v: float | None) -> bool:
    """欧赔合理区间；排除凯利指数(常 0.7–1.0)与概率小数。"""
    return v is not None and 1.01 <= v <= 80.0


def _is_plausible_ah_water(v: float | None) -> bool:
    """亚盘水位常见 0.5–2.5；过宽则拒。"""
    return v is not None and 0.30 <= v <= 3.50


def _is_plausible_ou_line(v: float | None) -> bool:
    """大小球盘口合理区间：0.5–6.5 球；过低小数按凯利列处理。"""
    return v is not None and 1.0 <= v <= 6.5


def _is_plausible_ou_water(v: float | None) -> bool:
    """大小球水位与亚盘水位区间一致。"""
    return v is not None and 0.30 <= v <= 3.50


# live.500 常见：联赛/阶段名被拆成「主客」
_DIRTY_TEAM_EXACT = frozenset({
    # 洲际/国际杯赛（单名占位）
    "欧罗巴", "欧联杯", "欧会杯", "欧冠", "欧冠杯", "亚冠", "亚冠杯", "欧超杯",
    "解放者杯", "南美杯", "世界杯", "世俱杯",
    # 联赛简称占位
    "日职", "日职联", "韩K", "英超", "西甲", "意甲", "德甲", "法甲",
    "英冠", "英甲", "英乙", "西乙", "德乙", "德丙", "意乙", "法乙", "荷乙", "日乙",
    "荷甲", "葡超", "苏超", "美职", "澳超", "巴甲", "阿甲",
    # 赛段占位
    "附加赛", "决赛", "半决赛", "四分之一决赛", "八强", "四强",
    "资格赛", "预选赛",
})
_DIRTY_TEAM_SUBSTR = (
    # 赛段
    "资格赛", "附加赛", "预选赛", "季后赛", "小组赛", "淘汰赛",
    # 轮次（中文数字/阿拉伯数字）
    "第三轮", "第二轮", "第一轮", "第1轮", "第2轮", "第3轮",
    # 完整赛事名后缀
    "职业联赛", "超级联赛", "甲级联赛", "乙级联赛", "冠军联赛",
    "联赛", "杯赛",
    # 占位标记
    "(队名待核)", "队名待核",
    # 赛事名兜底（与 exact 互补）
    "欧罗巴", "欧联杯", "欧会杯", "欧冠杯", "亚冠", "解放者杯", "南美杯", "世界杯", "世俱杯",
)


def is_dirty_team_label(name: str) -> bool:
    """是否像联赛/轮次名，而非俱乐部名。"""
    n = (name or "").strip()
    if not n or len(n) < 2:
        return True
    if "VS" in n.upper() or "vs" in n:
        return True
    if n in _DIRTY_TEAM_EXACT:
        return True
    if any(s in n for s in _DIRTY_TEAM_SUBSTR):
        return True
    # 轮次兜底：第N轮 / 第X轮（避免误伤「第戎」等真实队名）
    if re.search(r"第[一二三四五六七八九十零〇\d]+轮", n):
        return True
    # 极短且以杯/联/超/冠/甲/乙/丙结尾，多半是赛事名（德乙、英甲）
    if len(n) <= 4 and n.endswith(("杯", "联", "超", "冠", "甲", "乙", "丙")):
        return True
    # 避免误伤真实俱乐部：若队名明显是「地名+职业联赛」等完整赛事名才判脏
    if n.endswith("职业联赛") or n.endswith("超级联赛") or n.endswith("甲级联赛") or n.endswith("乙级联赛"):
        return True
    return False


def needs_name_fix(fixture: MatchFixture) -> bool:
    home = (fixture.home or "").strip()
    away = (fixture.away or "").strip()
    if home and away and home == away:
        return True
    return is_dirty_team_label(home) or is_dirty_team_label(away)


def ensure_fixture_real_teams(session, fixture: MatchFixture) -> MatchFixture:
    """live 脏队名 → 分析页真实主客。干净原名不会被脏 fetched 名覆盖。失败则原样返回。"""
    from download_500 import fetch_match_info

    if not needs_name_fix(fixture):
        return fixture
    try:
        info = fetch_match_info(session, str(fixture.fixture_id))
    except Exception as exc:
        log.warning("fetch_match_info 队名修正失败 fid=%s: %s", fixture.fixture_id, exc)
        return fixture
    if not info.home or not info.away:
        return fixture
    if is_dirty_team_label(info.home) and is_dirty_team_label(info.away):
        return fixture

    before = (fixture.home, fixture.away)
    same_name = (fixture.home or "").strip() == (fixture.away or "").strip() and bool((fixture.home or "").strip())
    fetched_pair_ok = (
        bool(info.home and info.away)
        and info.home.strip() != info.away.strip()
        and not is_dirty_team_label(info.home)
        and not is_dirty_team_label(info.away)
    )
    if same_name and fetched_pair_ok:
        fixture.home = info.home
        fixture.away = info.away
    else:
        # 仅当 fetched 名为干净且优于原名时才覆盖
        if is_dirty_team_label(fixture.home or "") and not is_dirty_team_label(info.home):
            fixture.home = info.home
        if is_dirty_team_label(fixture.away or "") and not is_dirty_team_label(info.away):
            fixture.away = info.away
    if getattr(info, "label", None):
        fixture.label = info.label
    if (fixture.home, fixture.away) != before:
        log.info(
            "队名修正 fid=%s → %s vs %s",
            fixture.fixture_id, fixture.home, fixture.away,
        )
    return fixture


# 统一对外名：poll_service / poll_single_fixture 只调这一处
ensure_fixture_identity = ensure_fixture_real_teams


def _pick_row(rows: list[str], *patterns: str) -> list[str] | None:
    for row in rows:
        head = row.split("|", 1)[0]
        for pat in patterns:
            if re.search(pat, head, re.I):
                return row.split("|")
    return None


def _parse_ah_row(cells: list[str]) -> dict[str, Any]:
    # name|home|line|away|time|open_home|open_line|open_away|open_time
    line = parse_handicap(cells[2]) if len(cells) > 2 else None
    open_line = parse_handicap(cells[6]) if len(cells) > 6 else None
    hw = _to_float(cells[1]) if len(cells) > 1 else None
    aw = _to_float(cells[3]) if len(cells) > 3 else None
    oh = _to_float(cells[5]) if len(cells) > 5 else None
    oa = _to_float(cells[7]) if len(cells) > 7 else None
    return {
        "ah_line": line,
        "ah_home_water": hw if _is_plausible_ah_water(hw) else hw,
        "ah_away_water": aw if _is_plausible_ah_water(aw) else aw,
        "ah_open_line": open_line if open_line is not None else line,
        "ah_open_home": oh if _is_plausible_ah_water(oh) else None,
        "ah_open_away": oa if _is_plausible_ah_water(oa) else None,
    }


def _find_eu_open_triple(cells: list[str]) -> tuple[float | None, float | None, float | None]:
    """在即时 H/D/A 之后，寻找第二组像欧赔的三元组当作公司初盘。

    现网百家页前段常是：赔三列 + 概率% + 返还率 + 凯利(0.7–1.0)。
    凯利不可当 open；仅当存在 1.01–80 的第二组三列才记入 eu_open_*。
    """
    # 从 index 4 起滑窗（跳过主即时三列 1..3）
    for i in range(4, max(4, len(cells) - 2)):
        h, d, a = _to_float(cells[i]), _to_float(cells[i + 1]), _to_float(cells[i + 2])
        if _is_plausible_eu_odds(h) and _is_plausible_eu_odds(d) and _is_plausible_eu_odds(a):
            return h, d, a
    return None, None, None


def _parse_eu_row(cells: list[str]) -> dict[str, Any]:
    h = _to_float(cells[1]) if len(cells) > 1 else None
    d = _to_float(cells[2]) if len(cells) > 2 else None
    a = _to_float(cells[3]) if len(cells) > 3 else None
    # 经典错位：cells[8:11] 现网多为凯利，不是初盘
    oh, od, oa = _find_eu_open_triple(cells)
    if (
        oh is None
        and len(cells) > 10
        and _is_plausible_eu_odds(_to_float(cells[8]))
        and _is_plausible_eu_odds(_to_float(cells[9]))
        and _is_plausible_eu_odds(_to_float(cells[10]))
    ):
        oh, od, oa = _to_float(cells[8]), _to_float(cells[9]), _to_float(cells[10])
    return {
        "eu_home": h if _is_plausible_eu_odds(h) else None,
        "eu_draw": d if _is_plausible_eu_odds(d) else None,
        "eu_away": a if _is_plausible_eu_odds(a) else None,
        "eu_open_home": oh,
        "eu_open_draw": od,
        "eu_open_away": oa,
    }


def _parse_ou_row(cells: list[str]) -> dict[str, Any]:
    """大小球平均值行：cell[1]=平均值, [3]=大, [4]=盘口, [5]=小, [9]=初大, [10]=初盘, [11]=初小。"""
    over = _to_float(cells[3]) if len(cells) > 3 else None
    line = _to_float(cells[4]) if len(cells) > 4 else None
    under = _to_float(cells[5]) if len(cells) > 5 else None
    oover = _to_float(cells[9]) if len(cells) > 9 else None
    oline = _to_float(cells[10]) if len(cells) > 10 else None
    ounder = _to_float(cells[11]) if len(cells) > 11 else None
    valid = _is_plausible_ou_line(line) and _is_plausible_ou_water(over) and _is_plausible_ou_water(under)
    # 初盘必须三件套同时合法，防止把凯利/概率列误填成部分 open
    open_valid = (
        valid
        and _is_plausible_ou_line(oline)
        and _is_plausible_ou_water(oover)
        and _is_plausible_ou_water(ounder)
    )
    return {
        "ou_line": line if valid else None,
        "ou_over": over if valid else None,
        "ou_under": under if valid else None,
        "ou_open_line": oline if open_valid else None,
        "ou_open_over": oover if open_valid else None,
        "ou_open_under": ounder if open_valid else None,
    }


def _fetch_ou_html(session, fixture_id: str, *, guard: ScraperGuard) -> dict[str, Any] | None:
    """抓取大小球分析页；无数据返回 None，失败不阻断欧亚。"""
    fid = str(fixture_id)
    url = f"{BASE}/fenxi/daxiao-{fid}.shtml"
    try:
        html = get_text(session, url, source="500", guard=guard)
    except Exception as exc:
        log.debug("大小球页获取失败 fid=%s: %s", fid, exc)
        return None
    if "大小球" not in html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) >= 11 and tds[1].get_text(strip=True) == "平均值":
            cells = [c.get_text(strip=True) for c in tds]
            parsed = _parse_ou_row(cells)
            if parsed.get("ou_line") is not None:
                return parsed
    return None


def fetch_odds_html(
    session,
    fixture_id: str,
    *,
    guard: ScraperGuard,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """抓取 500.com 欧赔/亚盘分析页。

    500 对庄名打码（如 官*官*、威***威***），不能按明文匹配。
    改为：按行结构解析——能提取合法赔率浮点的行即为有效行。
    优先 Pi/平博/平均值（若匹配），否则取第一条有效行。
    欧、亚任一成功即可；两侧都失败才报错。
    """
    fid = str(fixture_id)
    ah_url = f"{BASE}/fenxi/yazhi-{fid}.shtml"
    eu_url = f"{BASE}/fenxi/ouzhi-{fid}.shtml"

    ah_html = get_text(session, ah_url, source="500", guard=guard)
    eu_html = get_text(session, eu_url, source="500", guard=guard)

    ah_soup = BeautifulSoup(ah_html, "html.parser")
    eu_soup = BeautifulSoup(eu_html, "html.parser")
    ah_rows = _serialize_xls_table(ah_soup)["row"]
    eu_rows = _serialize_xls_table(eu_soup)["row"]

    # 欧赔：优先明文匹配，回退按结构解析
    eu_cells = _pick_row(eu_rows, r"Pi|平博|Pinnacle") or _pick_row(eu_rows, "平均值")
    eu_bookmaker = "pinnacle" if (eu_cells and re.search(r"Pi|平博", eu_cells[0], re.I)) else "average"
    if not eu_cells:
        eu_cells = _pick_first_valid_eu_row(eu_rows)
        eu_bookmaker = "first_valid"

    # 亚盘：优先明文匹配，回退按结构解析
    ah_cells = _pick_row(ah_rows, r"Pi|平博|Pinnacle") or _pick_row(ah_rows, "平均值")
    ah_bookmaker = "pinnacle" if (ah_cells and re.search(r"Pi|平博", ah_cells[0], re.I)) else "average"
    if not ah_cells:
        ah_cells = _pick_first_valid_ah_row(ah_rows)
        ah_bookmaker = "first_valid"

    if not eu_cells and not ah_cells:
        raise RuntimeError(f"欧赔/亚盘均无有效行 fid={fid}")

    # 缺一侧不报错，用空 dict 填充
    ah = _parse_ah_row(ah_cells) if ah_cells else {}
    eu = _parse_eu_row(eu_cells) if eu_cells else {}
    eu_books = parse_eu_bookmakers(eu_rows) if eu_rows else []
    ah["bookmaker"] = ah_bookmaker
    eu["bookmaker"] = eu_bookmaker
    eu["eu_books"] = eu_books
    ah["eu_books"] = eu_books
    return ah, eu


def _pick_first_valid_eu_row(rows: list[str]) -> list[str] | None:
    """从欧赔表取第一条能解析出 3 个合法赔率浮点的行。"""
    for row in rows:
        cells = row.split("|")
        if len(cells) < 4:
            continue
        vals = [_to_float(cells[i]) for i in range(1, 4)]
        if all(v is not None and v > 1.0 for v in vals):
            return cells
    return None


def _pick_first_valid_ah_row(rows: list[str]) -> list[str] | None:
    """从亚盘表取第一条能解析出盘口线+水位的行。

    AH row: bookmaker|home_water|line|away_water|time|...
    line 可能是 "受半球"、"平手"、"半球"、"受平手/半球升" 等
    """
    for row in rows:
        cells = row.split("|")
        if len(cells) < 4:
            continue
        line_raw = cells[2] if len(cells) > 2 else ""
        if not line_raw or line_raw in ("盘口", "赔率"):
            continue
        line = parse_handicap(line_raw)
        hw = _to_float(cells[1])
        aw = _to_float(cells[3])
        if line is not None or (hw is not None and aw is not None):
            return cells
    return None


def build_tick(
    fixture: MatchFixture,
    ah: dict[str, Any],
    eu: dict[str, Any],
    *,
    jingcai: dict[str, Any] | None = None,
    betfair: dict[str, Any] | None = None,
    ou: dict[str, Any] | None = None,
) -> dict[str, Any]:
    jc = jingcai or {}
    bf = betfair or {}
    ou = ou or {}
    merged = {
        "bookmaker": ah.get("bookmaker") or eu.get("bookmaker") or "pinnacle",
        **ah,
        **eu,
        **ou,
        "raw_meta": {
            "external_id": fixture.fixture_id,
            "match_name": fixture.base_name,
            "match_num": fixture.match_num or jc.get("match_num"),
            "jingcai": jc,
            "betfair": bf,
            "eu_books": eu.get("eu_books") or [],
            "eu_books_major": select_major_eu_books(eu.get("eu_books") or []),
            "ou": {
                "has_data": ou.get("ou_line") is not None,
                "ou_line": ou.get("ou_line"),
                "ou_over": ou.get("ou_over"),
                "ou_under": ou.get("ou_under"),
                "ou_open_line": ou.get("ou_open_line"),
                "ou_open_over": ou.get("ou_open_over"),
                "ou_open_under": ou.get("ou_open_under"),
            },
        },
    }
    key = {
        k: merged.get(k)
        for k in (
            "bookmaker",
            "ah_line", "ah_home_water", "ah_away_water",
            "ah_open_line", "ah_open_home", "ah_open_away",
            "eu_home", "eu_draw", "eu_away",
            "eu_open_home", "eu_open_draw", "eu_open_away",
            "ou_line", "ou_over", "ou_under",
            "ou_open_line", "ou_open_over", "ou_open_under",
        )
    }
    key["eu_books_fp"] = eu_books_fingerprint(eu.get("eu_books") or [])
    # 竞彩 SP / 必发变动也要写新 tick，否则只改 SP 时时间线僵住
    key["jingcai"] = {
        "match_num": jc.get("match_num"),
        "has_sp": jc.get("has_sp"),
        "sp_home": jc.get("sp_home"),
        "sp_draw": jc.get("sp_draw"),
        "sp_away": jc.get("sp_away"),
        "has_rqsp": jc.get("has_rqsp"),
        "rqsp_home": jc.get("rqsp_home"),
        "rqsp_draw": jc.get("rqsp_draw"),
        "rqsp_away": jc.get("rqsp_away"),
        "handicap": jc.get("handicap"),
        "has_score_market": jc.get("has_score_market"),
        "score_odds": jc.get("score_odds"),
        "total_goals_odds": jc.get("total_goals_odds"),
    }
    key["betfair"] = {
        "volume_home": bf.get("volume_home"),
        "volume_draw": bf.get("volume_draw"),
        "volume_away": bf.get("volume_away"),
        "volume_total": bf.get("volume_total"),
        "volume_pct": bf.get("volume_pct"),
    }
    merged["tick_hash"] = hashlib.sha256(
        json.dumps(key, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]
    return merged


def assert_tick_has_markets(tick: dict[str, Any], *, fixture_id: str = "") -> None:
    """无有效欧亚不准当成功抓取：欧需三向齐全，亚需 line + 双水。"""
    has_eu = (
        _is_plausible_eu_odds(_to_float(tick.get("eu_home")))
        and _is_plausible_eu_odds(_to_float(tick.get("eu_draw")))
        and _is_plausible_eu_odds(_to_float(tick.get("eu_away")))
    )
    has_ah = (
        tick.get("ah_line") is not None
        and _is_plausible_ah_water(_to_float(tick.get("ah_home_water")))
        and _is_plausible_ah_water(_to_float(tick.get("ah_away_water")))
    )
    if not has_eu and not has_ah:
        raise RuntimeError(f"欧亚均为空或非法 fid={fixture_id or '?'}")


def poll_fixture(
    session,
    fixture: MatchFixture,
    *,
    guard: ScraperGuard,
    live_odds: dict[str, dict] | None = None,
    jczq_meta: dict[str, dict] | None = None,
) -> dict[str, Any]:
    fixture = ensure_fixture_identity(session, fixture)
    ah, eu = fetch_odds_html(session, fixture.fixture_id, guard=guard)
    ou = _fetch_ou_html(session, fixture.fixture_id, guard=guard) or {}
    jc = build_jingcai_snapshot(
        fixture.fixture_id,
        live_odds or {},
        order_id=fixture.order_id,
        jczq_meta=jczq_meta,
    )
    bf = fetch_betfair_snapshot(session, fixture.fixture_id)
    tick = build_tick(fixture, ah, eu, jingcai=jc, betfair=bf, ou=ou)
    assert_tick_has_markets(tick, fixture_id=str(fixture.fixture_id))
    return tick


def list_upcoming_fixtures(*, within_days: float = 2) -> list[MatchFixture]:
    session = make_session()
    return fetch_live_fixtures(session, within_days=within_days)


def fetch_jingcai_context(session) -> tuple[dict[str, dict], dict[str, dict]]:
    """One live page + one trade page per poll round."""
    live_odds = fetch_live_odds_list(session)
    try:
        jczq_meta = fetch_jczq_meta_by_order(session)
    except Exception as exc:
        log.warning("竞彩元数据抓取失败: %s", exc)
        jczq_meta = {}
    return live_odds, jczq_meta


def poll_single_fixture(
    fixture_id: str,
    *,
    output_root=None,
    within_days: float = 14,
) -> dict[str, Any]:
    """补抓单场：写 Postgres odds_ticks，返回 DB 时间线 match index。

    serve ``POST /api/match/{fid}/poll`` 调用此入口。``output_root`` 仅兼容占位。
    """
    from db.connection import ensure_schema, ping
    from db.repository import insert_tick_if_changed, upsert_fixture
    from db_timeline import load_match_index_from_db
    from download_500 import MatchFixture, extract_fixture_id, fetch_match_info

    del output_root  # 当前只写 DB 时间线
    fid = extract_fixture_id(str(fixture_id))
    if not ping():
        raise RuntimeError("数据库未连接，无法补抓（请先 docker compose up -d db）")
    ensure_schema()

    session = make_session()
    guard = ScraperGuard(min_delay=1.0, max_delay=2.0)

    # 1) 尽量从 live 列表拿到对阵 / order_id；失败则只靠分析页队名
    fx: MatchFixture | None = None
    try:
        live = fetch_live_fixtures(session, within_days=within_days, leagues=None)
        for cand in live:
            if str(cand.fixture_id) == fid:
                fx = cand
                break
    except Exception as exc:
        log.warning("live 列表查找 fid=%s 失败: %s", fid, exc)

    if fx is None:
        try:
            fx = fetch_match_info(session, fid)
        except Exception as exc:
            log.warning("fetch_match_info fid=%s 失败: %s", fid, exc)
            fx = MatchFixture(fixture_id=fid)

    fx = ensure_fixture_identity(session, fx)

    # 2) 竞彩上下文（失败不阻断欧亚）
    live_odds: dict[str, dict] = {}
    jczq_meta: dict[str, dict] = {}
    try:
        live_odds, jczq_meta = fetch_jingcai_context(session)
    except Exception as exc:
        log.warning("jingcai context fid=%s: %s", fid, exc)

    # 3) 抓亚欧 + 必发（poll_fixture 内校验非空）
    tick = poll_fixture(
        session, fx, guard=guard, live_odds=live_odds, jczq_meta=jczq_meta,
    )

    db_id = upsert_fixture(
        source="500",
        external_id=fid,
        home_team=fx.home or "",
        away_team=fx.away or "",
        match_name=fx.base_name,
        kickoff_at=fx.kickoff,
    )
    inserted = insert_tick_if_changed(db_id, tick, source="500")
    log.info(
        "单场补抓 fid=%s inserted=%s eu=%s ah_line=%s",
        fid, inserted, tick.get("eu_home"), tick.get("ah_line"),
    )

    idx = load_match_index_from_db(fid)
    if not idx:
        # 最小返回，避免 serve 再炸
        idx = {
            "fixture_id": fid,
            "match_name": fx.base_name,
            "timeline": [{"odds": {
                k: tick.get(k) for k in (
                    "eu_home", "eu_draw", "eu_away",
                    "ah_line", "ah_home_water", "ah_away_water",
                    "ou_line", "ou_over", "ou_under",
                    "ou_open_line", "ou_open_over", "ou_open_under",
                )
            }}],
            "point_count": 1,
            "source": "postgresql",
        }
    return idx
