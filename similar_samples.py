"""Compact historical similar-sample blocks for match detail pages."""

from __future__ import annotations

from ah_analytics import ah_breakdown

RESULT_CN = {"home": "主胜", "draw": "平", "away": "客胜"}


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _compact_sample(row: dict) -> dict:
    score_h = row.get("score_h")
    score_a = row.get("score_a")
    score = "—"
    try:
        score = f"{int(score_h)}-{int(score_a)}"
    except (TypeError, ValueError):
        pass
    return {
        "date": row.get("date"),
        "match": f"{row.get('home') or ''} vs {row.get('away') or ''}".strip(),
        "score": score,
        "result_cn": RESULT_CN.get(row.get("result_1x2"), row.get("result_1x2") or "—"),
        "ah": _fmt_num(row.get("ah_line")),
        "ah_water": (
            f"{_fmt_num(row.get('ah_home_water'))}/{_fmt_num(row.get('ah_away_water'))}"
            if row.get("ah_home_water") is not None or row.get("ah_away_water") is not None
            else "—"
        ),
        "eu": (
            f"{_fmt_num(row.get('eu_home'))}/{_fmt_num(row.get('eu_draw'))}/{_fmt_num(row.get('eu_away'))}"
            if row.get("eu_home") is not None
            else "—"
        ),
        "similarity": row.get("similarity_dist"),
        "source": "/".join(str(x) for x in (row.get("competition"), row.get("source")) if x),
    }


def _compact_block(stats: dict, *, title: str, source: str) -> dict:
    count = stats.get("count") or 0
    top_scores = stats.get("score_top") or []
    ah = ah_breakdown(stats) if count else {}
    rate_text = (
        f"主胜 {_pct(stats.get('home_win_rate'))} / "
        f"平 {_pct(stats.get('draw_rate'))} / "
        f"客胜 {_pct(stats.get('away_win_rate'))}"
    )
    if ah.get("ah_rate_text"):
        rate_text += f" · {ah['ah_rate_text']}"
    return {
        "title": title,
        "source": source,
        "count": count,
        "home_win_rate": stats.get("home_win_rate"),
        "draw_rate": stats.get("draw_rate"),
        "away_win_rate": stats.get("away_win_rate"),
        **ah,
        "rate_text": rate_text,
        "avg_total_goals": stats.get("avg_total_goals"),
        "top_scores": [
            {
                "score": x.get("score"),
                "pct": x.get("pct"),
                "count": x.get("count"),
            }
            for x in top_scores[:8] if isinstance(x, dict)
        ],
        "samples": [_compact_sample(x) for x in (stats.get("samples") or [])[:10]],
    }


def build_similarity_analysis(payload: dict) -> dict:
    """Return small, JSON-safe open/live comparison blocks."""
    return {
        "open": [
            _compact_block(payload.get("open_stats") or {}, title="初盘亚盘相似", source="open_ah"),
            _compact_block(payload.get("open_eu_stats") or {}, title="初盘欧赔相似", source="open_eu"),
        ],
        "live": [
            _compact_block(payload.get("stats") or {}, title="实时亚盘 vs 历史终盘相似", source="live_ah"),
            _compact_block(payload.get("eu_stats") or {}, title="实时欧赔 vs 历史终盘相似", source="live_eu"),
        ],
        "history_total": payload.get("history_total"),
        "auto_relaxed": payload.get("auto_relaxed", False),
    }
