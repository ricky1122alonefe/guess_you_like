"""Database read/write for fixtures and odds ticks."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from db.connection import cursor
from time_utils import format_beijing

log = logging.getLogger(__name__)


def upsert_fixture(
    *,
    source: str,
    external_id: str,
    home_team: str = "",
    away_team: str = "",
    match_name: str = "",
    kickoff_at: datetime | None = None,
) -> int:
    # 脏名不覆盖真名（与 poll_500 的 _DIRTY_TEAM_EXACT / _DIRTY_TEAM_SUBSTR 对齐；修改时请同步 poll_500.py）
    _dirty_exact = (
        "欧罗巴","欧联杯","欧会杯","欧冠","欧冠杯","亚冠","亚冠杯","欧超杯",
        "解放者杯","南美杯","世界杯","世俱杯",
        "日职","日职联","韩K","英超","西甲","意甲","德甲","法甲",
        "英冠","英甲","英乙","西乙","德乙","德丙","意乙","法乙","荷乙","日乙",
        "荷甲","葡超","苏超","美职","澳超","巴甲","阿甲",
        "附加赛","决赛","半决赛","四分之一决赛","八强","四强",
        "资格赛","预选赛",
    )
    _dirty_substr = (
        "资格赛", "附加赛", "预选赛", "季后赛", "小组赛", "淘汰赛",
        "第三轮", "第二轮", "第一轮", "第1轮", "第2轮", "第3轮",
        "职业联赛", "超级联赛", "甲级联赛", "乙级联赛", "冠军联赛",
        "联赛", "杯赛",
        "(队名待核)", "队名待核",
        "欧罗巴", "欧联杯", "欧会杯", "欧冠杯", "亚冠", "解放者杯", "南美杯", "世界杯", "世俱杯",
    )
    _exact_cond = " OR ".join(f"EXCLUDED.{{col}} = '{d}'" for d in _dirty_exact)
    _substr_cond = " OR ".join(f"EXCLUDED.{{col}} LIKE '%%{s}%%'" for s in _dirty_substr)
    # 第N轮 / 第X轮兜底（与 poll_500.is_dirty_team_label 正则对齐）
    _round_cond = "EXCLUDED.{col} ~ '第[一二三四五六七八九十零〇0-9]+轮'"

    def _guard(col: str) -> str:
        return (
            f"EXCLUDED.{col} = '' OR {_exact_cond.format(col=col)} OR "
            f"{_substr_cond.format(col=col)} OR {_round_cond.format(col=col)}"
        )

    home_guard = _guard("home_team")
    away_guard = _guard("away_team")
    name_guard = _guard("match_name")

    sql = f"""
    INSERT INTO fixtures (source, external_id, home_team, away_team, match_name, kickoff_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (source, external_id) DO UPDATE SET
        home_team = CASE WHEN {home_guard} OR (EXCLUDED.home_team <> '' AND EXCLUDED.home_team = EXCLUDED.away_team) THEN fixtures.home_team ELSE EXCLUDED.home_team END,
        away_team = CASE WHEN {away_guard} OR (EXCLUDED.away_team <> '' AND EXCLUDED.home_team = EXCLUDED.away_team) THEN fixtures.away_team ELSE EXCLUDED.away_team END,
        match_name = CASE WHEN {name_guard} THEN fixtures.match_name ELSE EXCLUDED.match_name END,
        kickoff_at = COALESCE(EXCLUDED.kickoff_at, fixtures.kickoff_at),
        updated_at = NOW()
    RETURNING id
    """
    with cursor() as cur:
        cur.execute(sql, (source, str(external_id), home_team, away_team, match_name, kickoff_at))
        row = cur.fetchone()
        return int(row["id"])


def get_latest_hash(fixture_db_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT tick_hash FROM odds_latest WHERE fixture_id = %s", (fixture_db_id,))
        row = cur.fetchone()
        return row["tick_hash"] if row else None


def insert_tick_if_changed(
    fixture_db_id: int,
    tick: dict[str, Any],
    *,
    source: str = "500",
) -> bool:
    """Insert odds_ticks + upsert odds_latest when hash differs. Returns True if inserted."""
    tick_hash = tick["tick_hash"]
    prev = get_latest_hash(fixture_db_id)
    if prev == tick_hash:
        return False

    cols = (
        "fixture_id", "source", "tick_hash",
        "ah_line", "ah_home_water", "ah_away_water",
        "ah_open_line", "ah_open_home", "ah_open_away",
        "eu_home", "eu_draw", "eu_away",
        "eu_open_home", "eu_open_draw", "eu_open_away",
        "bookmaker", "raw_meta",
    )
    vals = (
        fixture_db_id, source, tick_hash,
        tick.get("ah_line"), tick.get("ah_home_water"), tick.get("ah_away_water"),
        tick.get("ah_open_line"), tick.get("ah_open_home"), tick.get("ah_open_away"),
        tick.get("eu_home"), tick.get("eu_draw"), tick.get("eu_away"),
        tick.get("eu_open_home"), tick.get("eu_open_draw"), tick.get("eu_open_away"),
        tick.get("bookmaker", "pinnacle"),
        json.dumps(tick.get("raw_meta") or {}, ensure_ascii=False),
    )
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)

    upsert_latest = """
    INSERT INTO odds_latest (
        fixture_id, captured_at, tick_hash,
        ah_line, ah_home_water, ah_away_water,
        ah_open_line, ah_open_home, ah_open_away,
        eu_home, eu_draw, eu_away,
        eu_open_home, eu_open_draw, eu_open_away,
        bookmaker
    ) VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (fixture_id) DO UPDATE SET
        captured_at = EXCLUDED.captured_at,
        tick_hash = EXCLUDED.tick_hash,
        ah_line = EXCLUDED.ah_line,
        ah_home_water = EXCLUDED.ah_home_water,
        ah_away_water = EXCLUDED.ah_away_water,
        ah_open_line = EXCLUDED.ah_open_line,
        ah_open_home = EXCLUDED.ah_open_home,
        ah_open_away = EXCLUDED.ah_open_away,
        eu_home = EXCLUDED.eu_home,
        eu_draw = EXCLUDED.eu_draw,
        eu_away = EXCLUDED.eu_away,
        eu_open_home = EXCLUDED.eu_open_home,
        eu_open_draw = EXCLUDED.eu_open_draw,
        eu_open_away = EXCLUDED.eu_open_away,
        bookmaker = EXCLUDED.bookmaker
    """
    with cursor() as cur:
        cur.execute(f"INSERT INTO odds_ticks ({col_names}) VALUES ({placeholders})", vals)
        cur.execute(
            upsert_latest,
            (
                fixture_db_id, tick_hash,
                tick.get("ah_line"), tick.get("ah_home_water"), tick.get("ah_away_water"),
                tick.get("ah_open_line"), tick.get("ah_open_home"), tick.get("ah_open_away"),
                tick.get("eu_home"), tick.get("eu_draw"), tick.get("eu_away"),
                tick.get("eu_open_home"), tick.get("eu_open_draw"), tick.get("eu_open_away"),
                tick.get("bookmaker", "pinnacle"),
            ),
        )
    return True


def list_fixtures(*, source: str = "500", limit: int = 50) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.*, l.captured_at AS last_tick_at, l.tick_hash,
                   l.eu_home, l.eu_draw, l.eu_away,
                   l.ah_line, l.ah_home_water, l.ah_away_water
            FROM fixtures f
            LEFT JOIN odds_latest l ON l.fixture_id = f.id
            WHERE f.source = %s
            ORDER BY f.kickoff_at NULLS LAST, f.id
            LIMIT %s
            """,
            (source, limit),
        )
        return list(cur.fetchall())


def get_fixture_by_external(source: str, external_id: str) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM fixtures WHERE source = %s AND external_id = %s",
            (source, str(external_id)),
        )
        return cur.fetchone()


def list_ticks(fixture_db_id: int, *, limit: int = 500) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s
            ORDER BY captured_at ASC
            LIMIT %s
            """,
            (fixture_db_id, limit),
        )
        return list(cur.fetchall())


def get_closing_tick(fixture_db_id: int, kickoff_at: datetime | None) -> dict | None:
    """Last *valid* odds tick at or before kickoff (观测临盘/终盘快照).

    有效 tick：至少有完整欧三向 或 (ah_line 有值).
    kickoff_at 为 None 时取赛前最后一条并 log warning.
    """
    _valid = """
        (eu_home IS NOT NULL AND eu_home > 0 AND eu_away IS NOT NULL AND eu_away > 0)
        OR (ah_line IS NOT NULL)
    """
    if kickoff_at is None:
        with cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM odds_ticks
                WHERE fixture_id = %s AND ({_valid})
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (fixture_db_id,),
            )
            return cur.fetchone()
    with cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s AND captured_at <= %s AND ({_valid})
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (fixture_db_id, kickoff_at),
        )
        row = cur.fetchone()
        if row:
            return row
        cur.execute(
            """
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s
            ORDER BY captured_at ASC
            LIMIT 1
            """,
            (fixture_db_id,),
        )
        return cur.fetchone()


def list_fixtures_pending_settlement(
    *,
    source: str = "500",
    limit: int = 100,
    min_minutes_after_kickoff: float = 105,
) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.*
            FROM fixtures f
            LEFT JOIN match_results r ON r.fixture_id = f.id
            WHERE f.source = %s
              AND f.kickoff_at IS NOT NULL
              AND f.kickoff_at <= NOW() - (%s || ' minutes')::interval
              AND r.fixture_id IS NULL
            ORDER BY f.kickoff_at DESC
            LIMIT %s
            """,
            (source, str(min_minutes_after_kickoff), limit),
        )
        return list(cur.fetchall())


def list_fixtures_for_resettlement(
    *,
    source: str = "500",
    limit: int = 200,
    min_minutes_after_kickoff: float = 105,
) -> list[dict]:
    """Fixtures that already have match_results but may need score correction."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.*
            FROM fixtures f
            INNER JOIN match_results r ON r.fixture_id = f.id
            WHERE f.source = %s
              AND f.kickoff_at IS NOT NULL
              AND f.kickoff_at <= NOW() - (%s || ' minutes')::interval
            ORDER BY f.kickoff_at DESC
            LIMIT %s
            """,
            (source, str(min_minutes_after_kickoff), limit),
        )
        return list(cur.fetchall())


def _match_result_values(row: dict[str, Any]) -> tuple[Any, ...]:
    cols = (
        "fixture_id", "status", "home_score", "away_score", "score_text",
        "result_1x2", "result_1x2_cn",
        "closing_captured_at", "closing_ah_line", "closing_ah_home_water", "closing_ah_away_water",
        "closing_eu_home", "closing_eu_draw", "closing_eu_away",
        "closing_eu_open_home", "closing_eu_open_draw", "closing_eu_open_away",
        "closing_ou_line", "closing_ou_over", "closing_ou_under",
        "closing_ou_open_line", "closing_ou_open_over", "closing_ou_open_under",
        "pick_1x2_cn", "pick_ah_cn", "pick_jingcai_cn", "recommended_scores",
        "hit_1x2", "hit_score", "hit_ah", "ah_settlement", "hit_ou", "ou_settlement", "hit_jingcai",
        "payload", "source",
    )
    vals: list[Any] = []
    for col in cols:
        val = row.get(col)
        if col == "payload":
            val = json.dumps(val or {}, ensure_ascii=False, default=str)
        elif col == "recommended_scores" and val is not None and not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False) if isinstance(val, (list, dict)) else str(val)
        vals.append(val)
    return tuple(vals)


def upsert_match_result(fixture_db_id: int, row: dict[str, Any]) -> None:
    cols = (
        "fixture_id", "status", "home_score", "away_score", "score_text",
        "result_1x2", "result_1x2_cn",
        "closing_captured_at", "closing_ah_line", "closing_ah_home_water", "closing_ah_away_water",
        "closing_eu_home", "closing_eu_draw", "closing_eu_away",
        "closing_eu_open_home", "closing_eu_open_draw", "closing_eu_open_away",
        "closing_ou_line", "closing_ou_over", "closing_ou_under",
        "closing_ou_open_line", "closing_ou_open_over", "closing_ou_open_under",
        "pick_1x2_cn", "pick_ah_cn", "pick_jingcai_cn", "recommended_scores",
        "hit_1x2", "hit_score", "hit_ah", "ah_settlement", "hit_ou", "ou_settlement", "hit_jingcai",
        "payload", "source",
    )
    vals = _match_result_values(row)
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c != "fixture_id"
    )
    sql = f"""
    INSERT INTO match_results ({", ".join(cols)})
    VALUES ({placeholders})
    ON CONFLICT (fixture_id) DO UPDATE SET
        {updates},
        settled_at = NOW()
    """
    with cursor() as cur:
        cur.execute(sql, vals)


def get_match_result_by_external(source: str, external_id: str) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.*, f.external_id, f.match_name, f.kickoff_at
            FROM match_results r
            JOIN fixtures f ON f.id = r.fixture_id
            WHERE f.source = %s AND f.external_id = %s
            """,
            (source, str(external_id)),
        )
        return cur.fetchone()


def list_match_results_map(*, source: str = "500", limit: int = 200) -> dict[str, dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.*, f.external_id, f.match_name, f.kickoff_at,
                   f.home_team, f.away_team
            FROM match_results r
            JOIN fixtures f ON f.id = r.fixture_id
            WHERE f.source = %s
            ORDER BY r.settled_at DESC
            LIMIT %s
            """,
            (source, limit),
        )
        rows = cur.fetchall()
    return {str(r["external_id"]): {**dict(r), "fixture_id": str(r["external_id"])} for r in rows}


def get_opening_tick(fixture_db_id: int) -> dict | None:
    """First *valid* odds tick (观测初盘 = 本站最早有效快照).

    有效 tick：至少有完整欧三向 (eu_home + eu_draw + eu_away) 或 (ah_line 有值 + 双水).
    页内 eu_open_* / ah_open_* 是庄家初盘，此处仅返回观测初盘（本站首条）。
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s
              AND (
                (eu_home IS NOT NULL AND eu_home > 0 AND eu_away IS NOT NULL AND eu_away > 0)
                OR (ah_line IS NOT NULL)
              )
            ORDER BY captured_at ASC
            LIMIT 1
            """,
            (fixture_db_id,),
        )
        return cur.fetchone()


def list_tournament_results(*, source: str = "500", limit: int = 500) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.*, f.external_id, f.match_name, f.kickoff_at,
                   f.home_team, f.away_team
            FROM match_results r
            JOIN fixtures f ON f.id = r.fixture_id
            WHERE f.source = %s
            ORDER BY f.kickoff_at ASC NULLS LAST, r.settled_at ASC
            LIMIT %s
            """,
            (source, limit),
        )
        return list(cur.fetchall())


def get_scraper_state(key: str) -> dict:
    with cursor() as cur:
        cur.execute("SELECT value FROM scraper_state WHERE key = %s", (key,))
        row = cur.fetchone()
        if not row:
            return {}
        val = row["value"]
        if isinstance(val, str):
            return json.loads(val)
        return dict(val) if val else {}


def set_scraper_state(key: str, value: dict) -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO scraper_state (key, value, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (key, json.dumps(value, ensure_ascii=False)),
        )


def db_stats() -> dict:
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM fixtures")
        fixtures = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM odds_ticks")
        ticks = cur.fetchone()["n"]
        cur.execute("SELECT MAX(captured_at) AS t FROM odds_ticks")
        last_tick = cur.fetchone()["t"]
    return {
        "fixtures": fixtures,
        "ticks": ticks,
        "last_tick_at": format_beijing(last_tick) if last_tick else None,
    }
