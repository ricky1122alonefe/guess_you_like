"""Over/Under（大小球）参考轨 — 独立于 1X2/竞彩轨，不改竞彩方向。

产品定位：
- 数学（Dixon-Coles 矩阵 / 泊松 λ）只给基准概率，不构成可购结论。
- 有竞彩大小球 SP 时 devig 后算 edge；无则只报模型概率。
- 对照摘要只对「大小球建议」自身 hold / size_down / skip；禁止因此 flip 胜平负。
- buyable 永远 False（除非以后单独做竞彩大小球可购且用户明确）。
- 赛前暴雨等只作 note，不直接改 lean。
"""
from __future__ import annotations

import logging
import math
from typing import Any

from score_models import score_matrix

log = logging.getLogger(__name__)

_OU_CN = {"over": "大球", "under": "小球"}


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


def _signed_pct(n: float) -> str:
    return f"{n * 100:+.1f}%"


def _normalize_cells(raw: Any) -> dict[tuple[int, int], float] | None:
    """把 {f'{i}-{j}': p} 或 {(i,j): p} 矩阵归一化为 {(i,j): p}。"""
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[tuple[int, int], float] = {}
    for k, v in raw.items():
        p = _num(v)
        if p is None or p <= 0:
            continue
        if isinstance(k, tuple) and len(k) == 2:
            try:
                i, j = int(k[0]), int(k[1])
            except (TypeError, ValueError):
                continue
        elif isinstance(k, str) and "-" in k:
            left, right = k.split("-", 1)
            try:
                i, j = int(left), int(right)
            except (TypeError, ValueError):
                continue
        else:
            continue
        if i < 0 or j < 0:
            continue
        out[(i, j)] = p
    if not out:
        return None
    total = sum(out.values())
    if total <= 0:
        return None
    if abs(total - 1.0) > 1e-3:
        out = {k: v / total for k, v in out.items()}
    return out


def _cells_from_pred(pred: dict[str, Any]) -> dict[tuple[int, int], float] | None:
    """从 pred 提取比分矩阵（result_forecast.poisson_matrix 优先，quant.score_model λ 兜底）。"""
    if not isinstance(pred, dict):
        return None
    pm = (pred.get("result_forecast") or {}).get("secondary", {}).get("models", {}).get("poisson_matrix")
    if not isinstance(pm, dict):
        pm = pred.get("poisson_matrix")
    if isinstance(pm, dict):
        cells = _normalize_cells(pm.get("score_matrix"))
        if cells:
            return cells
    sm = (pred.get("quant") or {}).get("score_model")
    if isinstance(sm, dict):
        lam_h = _num(sm.get("lambda_home"))
        lam_a = _num(sm.get("lambda_away"))
        if lam_h and lam_a and lam_h > 0 and lam_a > 0:
            cells = score_matrix(lam_h, lam_a)
            if cells:
                return cells
    return None


def _total_metrics(cells: dict[tuple[int, int], float]) -> dict[str, Any]:
    """从矩阵计算各大小球线概率、BTTS、0-0、预期总进球。"""
    lines: dict[str, dict[str, float]] = {}
    for line in (1.5, 2.5, 3.5):
        over = sum(p for (i, j), p in cells.items() if i + j > line)
        over = min(1.0, max(0.0, over))
        lines[f"{line:g}"] = {"over": round(over, 4), "under": round(1.0 - over, 4)}
    btts = sum(p for (i, j), p in cells.items() if i >= 1 and j >= 1)
    zero_zero = cells.get((0, 0), 0.0)
    exp_total = sum((i + j) * p for (i, j), p in cells.items())
    return {
        "lines": lines,
        "btts": round(btts, 4),
        "zero_zero": round(zero_zero, 4),
        "exp_total": round(exp_total, 3),
    }


def _extract_ou_sp(pred: dict[str, Any]) -> dict[str, Any] | None:
    """竞彩大小球 SP（当前数据源无总进球/大小球 SP；防御支持未来字段）。"""
    if not isinstance(pred, dict):
        return None
    raw = None
    for key in ("ou_sp", "over_under_sp", "total_goals_sp"):
        candidate = pred.get(key)
        if isinstance(candidate, dict):
            raw = candidate
            break
    if raw is None:
        snap = pred.get("odds_snapshot")
        if isinstance(snap, dict):
            for key in ("ou_sp", "over_under_sp"):
                candidate = snap.get(key)
                if isinstance(candidate, dict):
                    raw = candidate
                    break
    if not isinstance(raw, dict):
        return None
    over = _num(raw.get("over") or raw.get("over_odds") or raw.get("大"))
    under = _num(raw.get("under") or raw.get("under_odds") or raw.get("小"))
    if not over or not under or over <= 1 or under <= 1:
        return None
    line = _num(raw.get("line")) or 2.5
    return {"line": line, "over": over, "under": under, "label": raw.get("label") or "大小球"}


def _devig_ou(over_odds: float, under_odds: float) -> dict[str, float]:
    """round-robin devig：隐含大/小概率。"""
    inv_over = 1.0 / over_odds
    inv_under = 1.0 / under_odds
    total = inv_over + inv_under
    if total <= 0:
        return {"p_over": 0.0, "p_under": 0.0, "margin": 0.0}
    return {
        "p_over": round(inv_over / total, 4),
        "p_under": round(inv_under / total, 4),
        "margin": round(total - 1.0, 4),
    }


def _weather_notes(pred: dict[str, Any]) -> list[str]:
    """赛前暴雨/大雨/大风只作 note，不直接改 lean。"""
    notes: list[str] = []
    dims = (pred.get("prematch_desk") or {}).get("dimensions") or []
    for d in dims:
        if not isinstance(d, dict) or d.get("id") != "weather" or d.get("missing"):
            continue
        txt = "；".join(str(x) for x in (d.get("evidence") or []))
        if any(k in txt for k in ("暴雨", "大暴雨", "大雨", "大风")):
            notes.append(f"赛前天气：{txt}")
    return notes


def build_ou_lane(pred: dict[str, Any]) -> dict[str, Any]:
    """构建大小球参考轨。

    Returns:
        {id, label, tag, missing, missing_reason, line, p_over, p_under,
         lines, btts, zero_zero, exp_total, lean, lean_cn, reasons,
         sp, implied, edge, buyable: False, notes}
    """
    missing = {
        "id": "ou",
        "label": "大小球轨",
        "tag": "参考·不可购",
        "missing": True,
        "missing_reason": "无泊松比分矩阵（λ/矩阵数据缺失）",
        "line": 2.5,
        "p_over": None,
        "p_under": None,
        "lines": {},
        "btts": None,
        "zero_zero": None,
        "exp_total": None,
        "lean": None,
        "lean_cn": "中性",
        "reasons": [],
        "sp": None,
        "implied": None,
        "edge": None,
        "buyable": False,
        "notes": [],
    }
    cells = _cells_from_pred(pred)
    if not cells:
        return missing

    m = _total_metrics(cells)
    over = m["lines"]["2.5"]["over"]
    under = m["lines"]["2.5"]["under"]

    reasons: list[str] = [
        f"泊松/Dixon-Coles 矩阵：P(大2.5)≈{_pct(over)} / P(小2.5)≈{_pct(under)}"
    ]
    if m["exp_total"] is not None:
        reasons.append(f"预期总进球≈{m['exp_total']:.2f}（λ主+λ客）")

    sp = _extract_ou_sp(pred)
    implied = None
    edge = None
    if sp:
        implied = _devig_ou(sp["over"], sp["under"])
        edge = {
            "over": round(over - implied["p_over"], 4),
            "under": round(under - implied["p_under"], 4),
        }
        reasons.append(
            f"竞彩大小球 SP {sp['over']}/{sp['under']} devig 后隐含大≈{_pct(implied['p_over'])}，"
            f"模型 edge 大≈{_signed_pct(edge['over'])}"
        )

    # lean 仅来自模型基准；SP 反向只进 edge/对照摘要，不直接改 lean。
    lean = None
    if over >= 0.60:
        lean = "over"
    elif under >= 0.60:
        lean = "under"

    return {
        "id": "ou",
        "label": "大小球轨",
        "tag": "参考·不可购",
        "missing": False,
        "missing_reason": None,
        "line": 2.5,
        "p_over": over,
        "p_under": under,
        "lines": m["lines"],
        "btts": m["btts"],
        "zero_zero": m["zero_zero"],
        "exp_total": m["exp_total"],
        "lean": lean,
        "lean_cn": _OU_CN.get(lean, "中性"),
        "reasons": reasons,
        "sp": sp,
        "implied": implied,
        "edge": edge,
        "buyable": False,
        "notes": _weather_notes(pred),
    }


def build_ou_comparison(ou: dict[str, Any]) -> dict[str, Any]:
    """大小球对照摘要：仅对「大小球建议」自身 hold / size_down / skip，不碰 1X2。"""
    if not ou or ou.get("missing"):
        return {
            "action": "hold",
            "buyable": False,
            "summary": "大小球参考轨无模型矩阵，不形成建议",
        }
    if not ou.get("sp") or not ou.get("edge"):
        return {
            "action": "hold",
            "buyable": False,
            "summary": (
                f"无竞彩大小球 SP，仅模型概率参考：P(大2.5)≈{_pct(ou.get('p_over') or 0)} / "
                f"P(小2.5)≈{_pct(ou.get('p_under') or 0)}；不影响竞彩 1X2"
            ),
        }
    edge = ou["edge"] or {}
    implied = ou.get("implied") or {}
    lean = ou.get("lean")
    # 严重反向：模型 lean 方向与 devig 后隐含概率 gap ≥20%（gap 为模型-隐含，正值表示
    # 市场强烈反向），才对「大小球建议」自身 size_down/skip；永不碰竞彩 1X2。
    if lean == "over" and (edge.get("over") or 0) >= 0.20:
        gap = edge["over"]
        action = "skip" if gap >= 0.30 else "size_down"
        verb = "放弃" if action == "skip" else "降为小注"
        summary = (
            f"模型看大（P大2.5≈{_pct(ou.get('p_over') or 0)}）但竞彩大小球 SP 隐含大仅≈"
            f"{_pct(implied.get('p_over') or 0)}，严重反向 → 大小球建议{verb}（不改竞彩 1X2）"
        )
    elif lean == "under" and (edge.get("under") or 0) >= 0.20:
        gap = edge["under"]
        action = "skip" if gap >= 0.30 else "size_down"
        verb = "放弃" if action == "skip" else "降为小注"
        summary = (
            f"模型看小（P小2.5≈{_pct(ou.get('p_under') or 0)}）但竞彩大小球 SP 隐含小仅≈"
            f"{_pct(implied.get('p_under') or 0)}，严重反向 → 大小球建议{verb}（不改竞彩 1X2）"
        )
    else:
        action = "hold"
        summary = "模型与竞彩大小球 SP 方向不冲突，大小球建议维持（仅参考，不可购，不改竞彩 1X2）"
    return {"action": action, "buyable": False, "summary": summary}


def attach_ou_lane(pred: dict[str, Any]) -> None:
    """挂载 pred['market_lanes']['ou'] 与 pred['market_lanes']['ou_comparison']。"""
    if not isinstance(pred, dict):
        return
    lanes = pred.setdefault("market_lanes", {})
    ou = build_ou_lane(pred)
    lanes["ou"] = ou
    lanes["ou_comparison"] = build_ou_comparison(ou)
