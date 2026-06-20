"""A/B/C buy tiers — 可串 / 可单关 / 仅参考."""

from __future__ import annotations

from typing import Any

from jingcai_pick import (
    KEY_FROM_SP_CN,
    NO_JINGCAI,
    actionable_jingcai_pick,
    final_recommendation_cn,
    jingcai_market_mode,
)

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_CN = {"A": "可串", "B": "可单关", "C": "仅参考"}
TIER_CSS = {"A": "tier-a", "B": "tier-b", "C": "tier-c"}
CN_TO_TIER = {v: k for k, v in TIER_CN.items()}
TIER_ORDER = ("A", "B", "C", "unknown")

DIVERGENCE_TAGS = frozenset({"出线·欧亚分歧", "竞彩·参考分歧"})
SKIP_PICKS = frozenset({"观望", "—", "", None, NO_JINGCAI})


def _pick_key_from_pred(pred: dict) -> str:
    jc = actionable_jingcai_pick(pred)
    if jc and jc.get("pick_key") not in (None, "skip"):
        return str(jc["pick_key"])
    cn = final_recommendation_cn(pred)
    return KEY_FROM_SP_CN.get(cn, "skip")


def _cn_for_key(key: str) -> str:
    from jingcai_pick import SP_CN
    return SP_CN.get(key, "—")


def compute_buy_tier(pred: dict) -> dict[str, Any]:
    """
    A 可串：中/高置信 + 参考=可购 + 无重大分歧 + 非「推平违初盘」
    B 可单关：竞彩可购 + 初盘/参考与可购方向一致（低置信也可）
    C 仅参考：观望、无竞彩、推平违初盘、分歧标签等
    """
    row = pred.get("predict_row") or {}
    pick_cn = final_recommendation_cn(pred)
    pick_key = _pick_key_from_pred(pred)
    conf = (row.get("置信度") or pred.get("confidence_cn") or "").strip()
    ref_cn = (
        pred.get("reference_result_1x2_cn")
        or row.get("赛果预测")
        or pred.get("match_result_1x2_cn")
        or pred.get("result_1x2_cn")
        or ""
    )
    open_cn = pred.get("open_result_1x2_cn") or row.get("初盘倾向") or ""
    tags = set(pred.get("alert_tags") or [])
    jc = actionable_jingcai_pick(pred)
    mode = jingcai_market_mode(pred.get("jingcai_snapshot")) or (
        (pred.get("jingcai_pick_info") or {}).get("jingcai_market")
    )
    reasons: list[str] = []

    if pick_cn in SKIP_PICKS or pick_key == "skip" or not jc:
        reasons.append("竞彩不可购或观望")
        return _tier_out(TIER_C, reasons, pick_key, parlay_ok=False)

    ref_key = KEY_FROM_SP_CN.get(ref_cn.strip(), "")
    open_key = KEY_FROM_SP_CN.get(open_cn.strip(), "")

    if tags & DIVERGENCE_TAGS:
        hit = "、".join(sorted(tags & DIVERGENCE_TAGS))
        reasons.append(f"存在{hit}")

    div = pred.get("jingcai_divergence")
    if isinstance(div, dict) and div.get("divergence"):
        reasons.append("竞彩SP与参考研判分歧")

    if pick_key == "draw" and open_key in ("home", "away") and open_key != "draw":
        reasons.append(f"推平局但初盘倾向{_cn_for_key(open_key)}")

    if pick_key == "draw" and ref_key in ("home", "away") and ref_key != "draw":
        reasons.append(f"推平局但参考研判{_cn_for_key(ref_key)}")

    if ref_key and pick_key and ref_key != pick_key:
        reasons.append(f"可购{_cn_for_key(pick_key)}与参考{_cn_for_key(ref_key)}不一致")

    if conf == "低" and not reasons:
        reasons.append("置信偏低，宜控制仓位")

    if reasons:
        # C if hard blockers, else B if only soft (low conf alone with alignment)
        hard = any(
            kw in " ".join(reasons)
            for kw in ("不可购", "分歧", "推平局但", "不一致", "出线", "竞彩SP")
        )
        if hard:
            return _tier_out(TIER_C, reasons, pick_key, parlay_ok=False)
        if open_key == pick_key or ref_key == pick_key:
            return _tier_out(TIER_B, reasons, pick_key, parlay_ok=False)
        return _tier_out(TIER_C, reasons, pick_key, parlay_ok=False)

    aligned = (not ref_key or ref_key == pick_key) and (not open_key or open_key == pick_key)
    if conf in ("高", "中") and aligned and mode == "sp":
        return _tier_out(TIER_A, ["中/高置信且参考与初盘一致"], pick_key, parlay_ok=True)

    if aligned or open_key == pick_key:
        note = ["低置信但方向与初盘/参考一致"] if conf == "低" else ["方向一致，可小注单关"]
        return _tier_out(TIER_B, note, pick_key, parlay_ok=False)

    return _tier_out(TIER_B, ["竞彩可购"], pick_key, parlay_ok=False)


def _tier_out(tier: str, reasons: list[str], pick_key: str, *, parlay_ok: bool) -> dict[str, Any]:
    return {
        "buy_tier": tier,
        "buy_tier_cn": TIER_CN[tier],
        "buy_tier_css": TIER_CSS[tier],
        "buy_tier_reason": "；".join(reasons[:3]),
        "parlay_eligible": parlay_ok,
        "pick_key": pick_key,
    }


def attach_buy_tier(pred: dict) -> dict:
    info = compute_buy_tier(pred)
    pred["buy_tier"] = info["buy_tier"]
    pred["buy_tier_cn"] = info["buy_tier_cn"]
    pred["buy_tier_reason"] = info["buy_tier_reason"]
    pred["parlay_eligible"] = info["parlay_eligible"]
    pred["buy_tier_info"] = info

    row = dict(pred.get("predict_row") or {})
    row["购买档位"] = info["buy_tier_cn"]
    row["档位说明"] = info["buy_tier_reason"]
    pred["predict_row"] = row
    return pred


def _apply_tier_to_record(rec: dict, info: dict[str, Any]) -> str:
    tier = info.get("buy_tier") or "unknown"
    rec["buy_tier"] = tier
    rec["buy_tier_cn"] = info.get("buy_tier_cn") or TIER_CN.get(tier, "未分级")
    rec["buy_tier_reason"] = info.get("buy_tier_reason") or ""
    rec["parlay_eligible"] = info.get("parlay_eligible") is True
    return tier


def resolve_record_buy_tier(rec: dict, *, output_root=None) -> str:
    """Resolve A/B/C for a settled ledger row; mutates rec in place."""
    tier = rec.get("buy_tier")
    if tier in ("A", "B", "C"):
        rec["buy_tier_cn"] = rec.get("buy_tier_cn") or TIER_CN[tier]
        return tier

    payload = rec.get("payload") or {}
    if isinstance(payload, str):
        import json
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    pred = payload.get("prediction") or {}

    for src in (pred, rec):
        t = src.get("buy_tier")
        if t in ("A", "B", "C"):
            return _apply_tier_to_record(rec, {
                "buy_tier": t,
                "buy_tier_cn": src.get("buy_tier_cn"),
                "buy_tier_reason": src.get("buy_tier_reason"),
                "parlay_eligible": src.get("parlay_eligible"),
            })
        row = src.get("predict_row") or {}
        cn = row.get("购买档位") or src.get("buy_tier_cn")
        if cn in CN_TO_TIER:
            return _apply_tier_to_record(rec, compute_buy_tier({**pred, **src, "predict_row": row}))

    if output_root and rec.get("fixture_id"):
        try:
            from prediction_archive import load_best_prediction

            full = load_best_prediction(output_root, str(rec["fixture_id"]))
            if full:
                if not full.get("buy_tier"):
                    from analysis.rules.output import attach_post_recommendation

                    attach_post_recommendation(full)
                return _apply_tier_to_record(rec, full.get("buy_tier_info") or full)
        except Exception:
            pass

    pick = rec.get("pick_jingcai_cn")
    if pick and pick not in SKIP_PICKS:
        stub = {
            **pred,
            "confidence_cn": rec.get("confidence_cn") or pred.get("confidence_cn"),
            "reference_result_1x2_cn": pred.get("reference_result_1x2_cn"),
            "open_result_1x2_cn": pred.get("open_result_1x2_cn"),
            "alert_tags": pred.get("alert_tags") or [],
            "jingcai_divergence": pred.get("jingcai_divergence") or {},
            "jingcai_pick_info": pred.get("jingcai_pick_info") or {},
            "jingcai_snapshot": pred.get("jingcai_snapshot") or rec.get("jingcai_snapshot"),
            "predict_row": {
                **(pred.get("predict_row") or {}),
                "竞彩推荐": pick,
                "置信度": rec.get("confidence_cn") or pred.get("confidence_cn") or "",
            },
        }
        return _apply_tier_to_record(rec, compute_buy_tier(stub))

    rec["buy_tier"] = "unknown"
    rec["buy_tier_cn"] = "未分级"
    rec["buy_tier_reason"] = ""
    rec["parlay_eligible"] = False
    return "unknown"


def enrich_records_buy_tier(records: list[dict], *, output_root=None) -> None:
    for rec in records:
        resolve_record_buy_tier(rec, output_root=output_root)
