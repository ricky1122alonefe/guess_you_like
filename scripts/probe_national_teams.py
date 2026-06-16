#!/usr/bin/env python3
"""Probe free national-team data coverage for 48 WC2026 teams."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from team_recent_form import canonical_team, _load_international_matches
from openfootball_intl import load_openfootball_matches, teams_in_openfootball


def _wc48() -> list[str]:
    data = json.loads((ROOT / "data" / "wc2026_groups.json").read_text(encoding="utf-8"))
    return sorted({t for g in data["groups"].values() for t in g})


def main() -> None:
    teams = _wc48()
    df = _load_international_matches()
    xlsx_teams = set()
    if not df.empty:
        xlsx_teams = set(df["home_cn"]) | set(df["away_cn"])

    of_matches = load_openfootball_matches()
    of_teams = teams_in_openfootball()

    rows = []
    for cn in teams:
        canon = canonical_team(cn)
        in_xlsx = canon in xlsx_teams or cn in xlsx_teams
        in_of = cn in of_teams or canon in of_teams
        rows.append({
            "team_cn": cn,
            "in_xlsx": in_xlsx,
            "in_openfootball": in_of,
            "covered_any": in_xlsx or in_of,
        })

    # proper form check per team via alias match name
    aliases = json.loads((ROOT / "data" / "wc2026_groups.json").read_text())["aliases"]
    for row in rows:
        cn = row["team_cn"]
        ens = aliases.get(cn, [cn])
        # count openfootball matches involving team
        of_n = sum(
            1 for m in of_matches
            if m["home_cn"] == cn or m["away_cn"] == cn
        )
        xlsx_n = 0
        if not df.empty:
            from team_recent_form import _team_mask
            xlsx_n = int(_team_mask(df, canonical_team(cn)).sum())
        row["xlsx_match_rows"] = xlsx_n
        row["openfootball_match_rows"] = of_n
        row["covered_any"] = xlsx_n > 0 or of_n > 0

    covered = sum(1 for r in rows if r["covered_any"])
    xlsx_only = sum(1 for r in rows if r["xlsx_match_rows"] > 0)
    of_only = sum(1 for r in rows if r["openfootball_match_rows"] > 0 and r["xlsx_match_rows"] == 0)

    api_key = bool(os.environ.get("API_FOOTBALL_KEY") or os.environ.get("APISPORTS_KEY"))
    report = {
        "teams_total": len(teams),
        "covered_local": covered,
        "xlsx_teams_with_rows": xlsx_only,
        "openfootball_only_teams": of_only,
        "openfootball_match_count": len(of_matches),
        "api_football_key_configured": api_key,
        "missing": [r["team_cn"] for r in rows if not r["covered_any"]],
        "teams": rows,
        "notes": [
            "WorldCup2026.xlsx = football-data 预选赛/国际赛（无东道主直邀队预选赛）",
            "openfootball = GitHub 免费 2026 小组赛+附加赛赛果文本",
            "API-Football 免费档需注册 dashboard.api-football.com 并设 API_FOOTBALL_KEY",
        ],
    }

    out = ROOT / "data" / "national_team_coverage.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"48 队覆盖（本地免费源）: {covered}/48")
    print(f"  xlsx 有记录: {xlsx_only}")
    print(f"  仅 openfootball 补足: {of_only}")
    print(f"  openfootball 解析场次: {len(of_matches)}")
    if report["missing"]:
        print("  仍缺失:", ", ".join(report["missing"]))
    print(f"  API-Football Key: {'已配置' if api_key else '未配置（注册后可补全友谊赛/统计）'}")
    print(f"报告: {out}")


if __name__ == "__main__":
    main()
