"""导出初盘/临盘统计表。

用法：
    python -m scripts.export_open_close_stats --days 30
    python -m scripts.export_open_close_stats --days 7 --json output.json
"""
from __future__ import annotations

import argparse
import json
import sys


def export_stats(days: int = 30) -> list[dict]:
    """导出近 N 天已 settle 且有 ≥2 ticks 的场。"""
    from db.connection import cursor
    from analysis.market.odds_lifecycle import get_match_odds_lifecycle

    with cursor() as cur:
        cur.execute(
            """
            SELECT f.external_id, f.home_team, f.away_team, f.kickoff_at,
                   mr.result_1x2, mr.home_score, mr.away_score,
                   (SELECT COUNT(*) FROM odds_ticks t WHERE t.fixture_id = f.id) AS tick_count
            FROM fixtures f
            JOIN match_results mr ON mr.fixture_id = f.id
            WHERE f.kickoff_at >= NOW() - (%s || ' days')::interval
              AND EXISTS (SELECT 1 FROM odds_ticks t WHERE t.fixture_id = f.id)
            ORDER BY f.kickoff_at DESC
            """,
            (str(days),),
        )
        rows = cur.fetchall()

    out = []
    for r in rows:
        if r["tick_count"] < 2:
            continue
        lc = get_match_odds_lifecycle(r["external_id"])
        op = lc.get("opening") or {}
        cl = lc.get("closing") or {}
        po = lc.get("p_open_devig") or {}
        pc = lc.get("p_close_devig") or {}
        move_home_pp = None
        if po.get("p_home") is not None and pc.get("p_home") is not None:
            move_home_pp = round((pc["p_home"] - po["p_home"]) * 100, 1)
        out.append({
            "fid": r["external_id"],
            "match": f"{r['home_team']} vs {r['away_team']}",
            "kickoff": str(r["kickoff_at"])[:16] if r["kickoff_at"] else "",
            "result_1x2": r["result_1x2"],
            "score": f"{r['home_score']}-{r['away_score']}",
            "open_eu": f"{op.get('eu_home','—')}/{op.get('eu_draw','—')}/{op.get('eu_away','—')}",
            "close_eu": f"{cl.get('eu_home','—')}/{cl.get('eu_draw','—')}/{cl.get('eu_away','—')}",
            "open_ah": op.get("ah_line", "—"),
            "close_ah": cl.get("ah_line", "—"),
            "p_open_home": round(po.get("p_home", 0) * 100, 1) if po.get("p_home") else None,
            "p_open_draw": round(po.get("p_draw", 0) * 100, 1) if po.get("p_draw") else None,
            "p_open_away": round(po.get("p_away", 0) * 100, 1) if po.get("p_away") else None,
            "p_close_home": round(pc.get("p_home", 0) * 100, 1) if pc.get("p_home") else None,
            "p_close_draw": round(pc.get("p_draw", 0) * 100, 1) if pc.get("p_draw") else None,
            "p_close_away": round(pc.get("p_away", 0) * 100, 1) if pc.get("p_away") else None,
            "move_home_pp": move_home_pp,
            "tick_count": r["tick_count"],
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="导出初盘/临盘统计表")
    parser.add_argument("--days", type=int, default=30, help="回溯天数（默认 30）")
    parser.add_argument("--json", dest="json_path", help="输出 JSON 文件路径")
    args = parser.parse_args()

    stats = export_stats(days=args.days)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print(f"已导出 {len(stats)} 场至 {args.json_path}")
    else:
        if not stats:
            print("无符合条件的场（已 settle + ≥2 ticks）")
            return
        # 打印表格
        print(f"{'fid':<12} {'比赛':<24} {'赛果':<6} {'初盘欧':<16} {'临盘欧':<16} {'初p主%':>6} {'临p主%':>6} {'变动':>6}")
        print("-" * 100)
        for s in stats:
            print(
                f"{s['fid']:<12} {s['match'][:22]:<24} {s['result_1x2']:<6} "
                f"{s['open_eu']:<16} {s['close_eu']:<16} "
                f"{s.get('p_open_home','—'):>6} {s.get('p_close_home','—'):>6} "
                f"{s.get('move_home_pp','—'):>6}"
            )


if __name__ == "__main__":
    main()
