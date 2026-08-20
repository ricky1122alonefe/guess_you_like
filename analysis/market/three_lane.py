"""Three-lane market view: EU / AH / Jingcai kept separate.

Rules:
- EU and AH lanes are reference only; they can warn against the Jingcai lane
  but must not replace its direction.
- Jingcai lane is the only buyable conclusion.
- Comparison can only hold / size_down / skip the Jingcai lane, never flip it.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from analysis.market.devig import devig_1x2
from eu_odds_chart import select_major_eu_books

log = logging.getLogger(__name__)

_OUTCOME_CN = {
    "home": "主胜",
    "draw": "平局",
    "away": "客胜",
    "skip": "观望",
    "none": "观望",
}


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
        return n if not math.isnan(n) else None
    except (TypeError, ValueError):
        return None


def _pct(n: float) -> str:
    return f"{n * 100:.1f}%"


def _mean_odds(books: list[dict[str, Any]]) -> dict[str, float] | None:
    totals: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
    for b in books:
        for k in totals:
            v = _num(b.get(k))
            if v is not None:
                totals[k].append(v)
    out: dict[str, float] = {}
    for k, vals in totals.items():
        if not vals:
            return None
        out[k] = sum(vals) / len(vals)
    return out


def _eu_books_major_from_pred(pred: dict[str, Any]) -> list[dict[str, Any]]:
    snap = pred.get("odds_snapshot") or {}
    major = snap.get("eu_books_major")
    if isinstance(major, list) and major:
        return major
    raw = pred.get("raw_meta") or {}
    books = raw.get("eu_books")
    if isinstance(books, list) and books:
        return select_major_eu_books(books)
    return []


def _load_eu_books_major(
    pred: dict[str, Any],
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
) -> list[dict[str, Any]]:
    major = _eu_books_major_from_pred(pred)
    if major:
        return major

    # Try DB timeline raw_meta if available.
    if fixture_id:
        try:
            from timeline_merge import load_latest_poll_meta

            meta = load_latest_poll_meta(str(fixture_id))
            books = (meta or {}).get("eu_books")
            if isinstance(books, list) and books:
                return select_major_eu_books(books)
        except Exception:
            log.debug("load_latest_poll_meta failed for %s", fixture_id, exc_info=True)

    # Fall back to parsing a cached EU xls under output_root.
    if output_root and fixture_id:
        try:
            return _parse_eu_xls_for_fixture(output_root, fixture_id)
        except Exception:
            log.debug("xls EU parse failed for %s", fixture_id, exc_info=True)

    return []


def _parse_eu_xls_for_fixture(
    output_root: str | Path,
    fixture_id: str,
) -> list[dict[str, Any]]:
    """Find the latest European odds xls for a fixture and parse book rows."""
    import pandas as pd

    root = Path(output_root)
    candidates = sorted(
        root.rglob(f"*{fixture_id}*欧洲数据.xls"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        # Match by fixture ID prefix fallback.
        candidates = sorted(
            root.rglob("*欧洲数据.xls"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:10]
    for path in candidates:
        books = _parse_eu_xls_to_books(path)
        if books:
            return select_major_eu_books(books)
    return []


def _parse_eu_xls_to_books(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_excel(str(path), header=None)
    books: list[dict[str, Any]] = []
    skip_prefixes = {"公司名称", "平均", "最大值", "最小值", "返回"}
    for _, row in df.iterrows():
        name = str(row[0]) if pd.notna(row[0]) else ""
        name = name.strip()
        if not name or any(name.startswith(p) for p in skip_prefixes):
            continue
        home = _num(row[1])
        draw = _num(row[2])
        away = _num(row[3])
        if home is None or draw is None or away is None:
            continue
        books.append({
            "name": name,
            "home": home,
            "draw": draw,
            "away": away,
        })
    return books


def build_eu_lane(
    pred: dict[str, Any],
    *,
    eu_books_major: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """European 1X2 lane from major bookmakers or snapshot average."""
    snap = pred.get("odds_snapshot") or {}
    major = eu_books_major if eu_books_major is not None else _eu_books_major_from_pred(pred)

    if major:
        mean = _mean_odds(major)
        source_books = [b.get("label") or b.get("name") for b in major if b.get("label") or b.get("name")]
    else:
        mean = {
            "home": _num(snap.get("eu_home")),
            "draw": _num(snap.get("eu_draw")),
            "away": _num(snap.get("eu_away")),
        }
        source_books = []
        if any(v is not None for v in mean.values()):
            source_books = ["欧赔均值"]

    missing = mean is None or any(v is None for v in mean.values())
    if missing:
        return {
            "id": "eu",
            "label": "欧赔轨",
            "tag": "参考·不可购",
            "buyable": False,
            "missing": True,
            "pick": "skip",
            "pick_cn": "观望",
            "p_pct": {},
            "reasons": ["暂无欧赔数据"],
            "source_books": [],
        }

    fair = devig_1x2(mean["home"], mean["draw"], mean["away"])
    p = {k: fair.get(k, 0.0) for k in ("home", "draw", "away")}
    pick = max(p, key=p.get)  # type: ignore[arg-type]
    pick_cn = _OUTCOME_CN.get(pick, pick)
    reasons = [
        f"去水隐含概率：主 {_pct(p['home'])} / 平 {_pct(p['draw'])} / 客 {_pct(p['away'])}",
        f"参考倾向：{pick_cn}",
    ]
    if source_books:
        reasons.append(f"来源：{' / '.join(source_books[:4])}")

    return {
        "id": "eu",
        "label": "欧赔轨",
        "tag": "参考·不可购",
        "buyable": False,
        "missing": False,
        "pick": pick,
        "pick_cn": pick_cn,
        "odds": mean,
        "p_pct": {k: round(v, 3) for k, v in p.items()},
        "reasons": reasons,
        "source_books": source_books,
    }


def build_ah_lane(pred: dict[str, Any]) -> dict[str, Any]:
    """Asian handicap lane from snapshot or pre-computed pick."""
    snap = pred.get("odds_snapshot") or {}
    line = _num(snap.get("ah_line"))
    home_w = _num(snap.get("ah_home_water"))
    away_w = _num(snap.get("ah_away_water"))
    if line is None and home_w is None and away_w is None:
        line = _num(pred.get("ah_line"))
        home_w = _num(pred.get("ah_home_water"))
        away_w = _num(pred.get("ah_away_water"))

    if line is None or (home_w is None and away_w is None):
        return {
            "id": "ah",
            "label": "亚盘轨",
            "tag": "参考·非竞彩让球",
            "buyable": False,
            "missing": True,
            "lean": "skip",
            "lean_cn": "观望",
            "line": None,
            "home_water": None,
            "away_water": None,
            "reasons": ["暂无亚盘数据"],
        }

    lean = pred.get("asian_handicap_pick")
    lean_cn = pred.get("asian_handicap_cn") or _OUTCOME_CN.get(lean) or "观望"
    reasons = [f"亚盘 {line} 主水 {home_w} 客水 {away_w}"]
    if lean and lean in ("home", "away"):
        reasons.append(f"参考方向：{lean_cn}")
    reasons.append("注：此处的『亚盘』不是竞彩让球胜平负")

    return {
        "id": "ah",
        "label": "亚盘轨",
        "tag": "参考·非竞彩让球",
        "buyable": False,
        "missing": False,
        "lean": lean if lean in ("home", "away") else "skip",
        "lean_cn": lean_cn,
        "line": line,
        "home_water": home_w,
        "away_water": away_w,
        "reasons": reasons,
    }


def build_jingcai_lane(pred: dict[str, Any]) -> dict[str, Any]:
    """Jingcai lane: the only buyable conclusion."""
    info = pred.get("jingcai_pick_info")
    if not info:
        try:
            from jingcai_pick import compute_jingcai_pick

            info = compute_jingcai_pick(pred)
        except Exception as exc:
            log.debug("compute_jingcai_pick failed: %s", exc)
            info = {"mode": "none", "pick": "skip"}
    if not isinstance(info, dict):
        info = {"mode": "none", "pick": "skip"}

    mode = info.get("mode") or "none"
    pick = info.get("pick") or "skip"
    if pick == "hold":
        pick = "skip"
    pick_cn = info.get("pick_cn") or _OUTCOME_CN.get(pick, "观望")
    play = {"sp": "胜平负", "rqsp": "让球胜平负", "none": "未开售"}.get(mode, mode)

    reasons: list[str] = []
    if mode == "sp":
        sp = info.get("sp") or pred.get("sp")
        reasons.append(f"胜平负 SP {sp} → {pick_cn}")
    elif mode == "rqsp":
        reasons.append(
            f"让球胜平负 {info.get('handicap', '')} {info.get('sp', '')} → {pick_cn}"
        )
    else:
        reasons.append("竞彩 SP 尚未开售或数据缺失")

    buyable = mode in ("sp", "rqsp") and pick in ("home", "draw", "away")

    return {
        "id": "jingcai",
        "label": "竞彩轨",
        "tag": "可购" if buyable else "未开售",
        "buyable": buyable,
        "missing": mode == "none",
        "mode": mode,
        "play": play,
        "pick": pick,
        "pick_cn": pick_cn,
        "sp": info.get("sp"),
        "handicap": info.get("handicap"),
        "reasons": reasons,
    }


def build_lane_comparison(
    eu: dict[str, Any],
    ah: dict[str, Any],
    jc: dict[str, Any],
) -> dict[str, Any]:
    """Code-generated comparison. Can only hold/size_down/skip the Jingcai lane."""
    if jc.get("missing") or jc.get("pick") == "skip":
        return {
            "agreement": "partial",
            "action": "hold",
            "summary": "竞彩轨数据不足，仅展示欧/亚参考。",
            "buyable": None,
        }

    jc_pick = jc.get("pick")
    signals: list[str] = []
    conflicts = 0
    if not eu.get("missing") and eu.get("pick") and eu.get("pick") != "skip":
        signals.append(eu["pick"])
        if eu["pick"] != jc_pick:
            conflicts += 1
    if not ah.get("missing") and ah.get("lean") and ah.get("lean") != "skip":
        signals.append(ah["lean"])
        if ah["lean"] != jc_pick:
            conflicts += 1

    all_present = (
        not eu.get("missing")
        and not ah.get("missing")
        and len(signals) == 2
        and all(s == jc_pick for s in signals)
    )

    if all_present:
        agreement = "align"
        action = "hold"
        summary = "三轨方向一致，竞彩轨维持原仓位建议。"
    elif conflicts == 0:
        agreement = "soft"
        action = "hold"
        summary = "可用轨方向一致，竞彩轨维持，继续观察欧洲公司变化。"
    elif conflicts == 1:
        agreement = "partial"
        action = "size_down"
        summary = "欧/亚至少一轨与竞彩方向冲突，竞彩仓位建议降小注。"
    else:
        agreement = "partial"
        action = "skip"
        summary = "欧/亚均与竞彩方向冲突，竞彩建议观望或放弃。"

    buyable: dict[str, Any] | None = None
    if jc.get("buyable") and action != "skip":
        buyable = {
            "market": jc.get("play"),
            "pick": jc.get("pick"),
            "pick_cn": jc.get("pick_cn"),
            "sp": jc.get("sp"),
            "reason": f"{jc.get('play')} {jc.get('sp')} → {jc.get('pick_cn')}",
        }

    return {
        "agreement": agreement,
        "action": action,
        "summary": summary,
        "buyable": buyable,
    }


def attach_market_lanes(
    pred: dict[str, Any],
    *,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
) -> None:
    """Attach {eu, ah, jingcai, comparison} to pred['market_lanes']."""
    if not isinstance(pred, dict):
        return

    major = _load_eu_books_major(pred, output_root=output_root, fixture_id=fixture_id)
    eu = build_eu_lane(pred, eu_books_major=major)
    ah = build_ah_lane(pred)
    jc = build_jingcai_lane(pred)
    comp = build_lane_comparison(eu, ah, jc)

    pred["market_lanes"] = {
        "eu": eu,
        "ah": ah,
        "jingcai": jc,
        "comparison": comp,
    }

    # Persist major books in odds_snapshot for downstream renderers.
    snap = pred.setdefault("odds_snapshot", {})
    if major and not snap.get("eu_books_major"):
        snap["eu_books_major"] = major
