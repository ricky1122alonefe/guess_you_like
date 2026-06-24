"""User locked 1X2 picks for World Cup group final round — immutable after finalize."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jingcai_pick import KEY_FROM_SP_CN
from share_card import NO_JINGCAI
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

PICKS_DIR = "user_final_picks"
PICKS_FILE = "picks.json"
OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
VALID_PICKS = frozenset({"home", "draw", "away"})


def pick_key_from_cn(pick_cn: str) -> str:
    pick = (pick_cn or "").strip()
    if not pick or pick in ("—", "观望", "暂无竞彩", NO_JINGCAI):
        return "skip"
    if pick in KEY_FROM_SP_CN:
        return KEY_FROM_SP_CN[pick]
    if pick.endswith(" 胜") or pick == "胜":
        return "home"
    if pick.endswith(" 平") or pick == "平":
        return "draw"
    if pick.endswith(" 负") or pick == "负":
        return "away"
    return "skip"


def pick_to_representative_score(pick: str) -> tuple[int, int]:
    """Minimal scores for group-table simulation from 1X2 only."""
    if pick == "home":
        return 1, 0
    if pick == "away":
        return 0, 1
    return 1, 1


def _picks_path(output_root: Path) -> Path:
    return output_root / "worldcup" / PICKS_DIR / PICKS_FILE


def load_user_picks(output_root: str | Path) -> dict[str, Any]:
    path = _picks_path(Path(output_root))
    if not path.is_file():
        return {"version": 1, "updated_at": None, "picks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("picks"), dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("读取用户定稿失败: %s", exc)
    return {"version": 1, "updated_at": None, "picks": {}}


def _save_user_picks(output_root: Path, data: dict[str, Any]) -> None:
    path = _picks_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_beijing_str()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_locked_pick(output_root: str | Path, fixture_id: str) -> dict[str, Any] | None:
    fid = str(fixture_id or "").strip()
    if not fid:
        return None
    pick = (load_user_picks(output_root).get("picks") or {}).get(fid)
    if pick and pick.get("locked"):
        return pick
    return None


def list_locked_picks(output_root: str | Path) -> list[dict[str, Any]]:
    picks = load_user_picks(output_root).get("picks") or {}
    out = [p for p in picks.values() if p.get("locked")]
    out.sort(key=lambda x: x.get("locked_at") or "", reverse=True)
    return out


def _normalize_pick_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    pick = str(item.get("pick") or item.get("outcome") or "").strip().lower()
    if pick not in VALID_PICKS:
        pick_cn = str(item.get("pick_cn") or "").strip()
        pick = pick_key_from_cn(pick_cn)
    if pick not in VALID_PICKS:
        return None
    fid = str(item.get("fixture_id") or "").strip()
    if not fid:
        return None
    return {
        "fixture_id": fid,
        "group": str(item.get("group") or "").strip().upper(),
        "home": str(item.get("home") or "").strip(),
        "away": str(item.get("away") or "").strip(),
        "match_name": str(item.get("match_name") or "").strip(),
        "kickoff": str(item.get("kickoff") or "").strip(),
        "pick": pick,
        "pick_cn": OUTCOME_CN[pick],
    }


def finalize_user_picks(
    output_root: str | Path,
    picks: list[dict[str, Any]],
    *,
    compare: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lock user 1X2 picks. Already-locked fixtures are rejected."""
    root = Path(output_root)
    store = load_user_picks(root)
    existing: dict[str, Any] = store.get("picks") or {}
    locked_now: list[dict[str, Any]] = []
    errors: list[str] = []
    compare_by_fid = {}
    if compare:
        for g in compare.get("groups") or []:
            for m in g.get("matches") or []:
                fid = str(m.get("fixture_id") or "").strip()
                if fid:
                    compare_by_fid[fid] = m

    for raw in picks or []:
        norm = _normalize_pick_item(raw)
        if not norm:
            errors.append(f"无效选项：{raw!r}")
            continue
        fid = norm["fixture_id"]
        if fid in existing and existing[fid].get("locked"):
            name = existing[fid].get("match_name") or fid
            errors.append(f"{name} 已定稿（{existing[fid].get('pick_cn')}），不可修改")
            continue
        entry = {
            **norm,
            "locked": True,
            "locked_at": now_beijing_str(),
        }
        if fid in compare_by_fid:
            cm = compare_by_fid[fid]
            entry["compare"] = {
                "ai_pick": cm.get("ai_pick"),
                "ai_agrees": cm.get("ai_agrees"),
                "rule_motivation_cn": cm.get("rule_motivation_cn"),
                "rule_direction_cn": cm.get("rule_direction_cn"),
                "rule_aligns": cm.get("rule_aligns"),
                "verdict_cn": cm.get("verdict_cn"),
            }
        existing[fid] = entry
        locked_now.append(entry)

    if not locked_now and errors:
        return {"ok": False, "error": errors[0], "errors": errors, "locked": []}

    store["picks"] = existing
    _save_user_picks(root, store)
    return {
        "ok": True,
        "locked_count": len(locked_now),
        "locked": locked_now,
        "errors": errors,
        "updated_at": store["updated_at"],
    }


def enrich_settled_with_user_pick(
    settled_row: dict[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Attach locked user pick and hit vs actual for review rows."""
    fid = str(settled_row.get("fixture_id") or "").strip()
    pick = get_locked_pick(output_root, fid)
    if not pick:
        return settled_row
    out = dict(settled_row)
    out["user_pick"] = pick.get("pick")
    out["user_pick_cn"] = pick.get("pick_cn")
    out["user_locked_at"] = pick.get("locked_at")
    out["user_compare"] = pick.get("compare") or {}
    actual = str(settled_row.get("result_1x2") or "").strip().lower()
    user_pick = pick.get("pick")
    if actual in VALID_PICKS and user_pick in VALID_PICKS:
        out["user_hit_1x2"] = actual == user_pick
    ai_key = pick_key_from_cn(
        (pick.get("compare") or {}).get("ai_pick")
        or settled_row.get("pick_jingcai_cn")
        or ""
    )
    if ai_key not in ("", "skip") and user_pick in VALID_PICKS:
        out["user_vs_ai_agree"] = ai_key == user_pick
    return out


def user_pick_accuracy(records: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [r for r in records if r.get("user_pick_cn") and r.get("user_hit_1x2") is not None]
    hit = sum(1 for r in judged if r.get("user_hit_1x2") is True)
    total = len(judged)
    vs_ai = [r for r in judged if r.get("user_vs_ai_agree") is not None]
    ai_same = sum(1 for r in vs_ai if r.get("user_vs_ai_agree") is True)
    return {
        "judged": total,
        "hit": hit,
        "rate_pct": round(100 * hit / total, 1) if total else None,
        "vs_ai_judged": len(vs_ai),
        "vs_ai_same": ai_same,
        "vs_ai_rate_pct": round(100 * ai_same / len(vs_ai), 1) if vs_ai else None,
    }
