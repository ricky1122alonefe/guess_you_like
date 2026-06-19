"""Attach parsed odds snapshot + EU implied metrics."""

from __future__ import annotations

from core.context import EnrichmentContext
from eu_implied_metrics import compute_eu_implied
from parser import parse_match_pair


class OddsSnapshotEnricher:
    id = "odds_snapshot"

    def run(self, ctx: EnrichmentContext) -> None:
        if not ctx.ah_path or not ctx.eu_path:
            return
        cur = parse_match_pair(str(ctx.ah_path), str(ctx.eu_path))
        ctx.pred["odds_snapshot"] = {
            "ah_line": cur.ah_line,
            "ah_open_line": cur.ah_open_line,
            "ah_home_water": cur.ah_home_water,
            "ah_away_water": cur.ah_away_water,
            "ah_open_home_water": cur.ah_open_home_water,
            "ah_open_away_water": cur.ah_open_away_water,
            "eu_home": cur.eu_home,
            "eu_draw": cur.eu_draw,
            "eu_away": cur.eu_away,
            "eu_open_home": cur.eu_open_home,
            "eu_open_draw": cur.eu_open_draw,
            "eu_open_away": cur.eu_open_away,
        }
        m = compute_eu_implied(cur.eu_home, cur.eu_draw, cur.eu_away)
        if m:
            ctx.pred["eu_implied"] = m.to_dict()
            ctx.pred["eu_implied_anomaly"] = m.is_anomaly
        if ctx.cur is None:
            ctx.cur = vars(cur)
