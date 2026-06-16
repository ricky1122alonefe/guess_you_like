"""Turn opening-pattern stats into human-readable conclusions for UI / AI."""

from __future__ import annotations

from typing import Any

from match_status import RESULT_CN

CONFIDENCE_NOTE = {
    "low": "样本较少，以下结论仅供观察，随赛程推进会更新",
    "medium": "样本逐步积累，结论可参考但需结合单场盘口",
    "high": "样本较充分，以下规律具有较高参考价值",
}


def _confidence(n: int) -> str:
    if n >= 20:
        return "high"
    if n >= 10:
        return "medium"
    return "low"


def _card(
    *,
    card_id: str,
    title: str,
    verdict: str,
    tone: str,
    one_liner: str,
    advice: str,
    evidence: str = "",
) -> dict[str, Any]:
    return {
        "id": card_id,
        "title": title,
        "verdict": verdict,
        "tone": tone,
        "one_liner": one_liner,
        "advice": advice,
        "evidence": evidence,
    }


def build_opening_conclusions(
    *,
    sample_size: int,
    stats: dict[str, Any],
    upset_matches: list[str],
    by_consistency: dict,
) -> dict[str, Any]:
    """Structured conclusion payload — UI renders cards, not raw tables."""
    n = sample_size
    conf = _confidence(n)
    cards: list[dict] = []
    actions: list[str] = []

    hr = stats.get("favorite_hit_rate_pct")
    fav_n = stats.get("favorite_samples") or 0
    if fav_n >= 2 and hr is not None:
        if hr < 45:
            cards.append(_card(
                card_id="favorite",
                title="初盘热门",
                verdict="警惕",
                tone="warn",
                one_liner=f"低赔项仅 {hr}% 打出，本届开局冷门偏多",
                advice="不要无脑跟初盘最低赔；需看亚盘是否配合",
                evidence=f"{fav_n} 场有明确低赔项",
            ))
            actions.append("初盘低赔≠稳胆，优先核对亚盘深浅与水位")
        elif hr >= 58:
            cards.append(_card(
                card_id="favorite",
                title="初盘热门",
                verdict="较可靠",
                tone="ok",
                one_liner=f"低赔项 {hr}% 打出，热门相对可信",
                advice="可适度跟随，但仍需避开诱盘场次",
                evidence=f"{fav_n} 场样本",
            ))
        else:
            cards.append(_card(
                card_id="favorite",
                title="初盘热门",
                verdict="一般",
                tone="neutral",
                one_liner=f"低赔打出率 {hr}%，无明显偏向",
                advice="热门与冷门均衡，按单场盘口判断",
                evidence=f"{fav_n} 场样本",
            ))

    draw_r = stats.get("draw_rate_pct")
    imp_d = stats.get("avg_implied_draw_pct")
    if draw_r is not None and n >= 3:
        if imp_d is not None and draw_r - imp_d >= 8:
            cards.append(_card(
                card_id="draw",
                title="平局倾向",
                verdict="偏多",
                tone="warn",
                one_liner=f"实际平局 {draw_r}% 高于初盘隐含 {imp_d}%",
                advice="实力接近或小组赛保守场次，可抬高平局权重",
                evidence=f"完赛 {n} 场",
            ))
            actions.append("小组赛平局率偏高，双选「胜+平」或直接博平可纳入考虑")
        elif draw_r >= 35:
            cards.append(_card(
                card_id="draw",
                title="平局倾向",
                verdict="留意",
                tone="neutral",
                one_liner=f"平局占比 {draw_r}%，不可忽视",
                advice="盘口偏浅或两队动机保守时，平局是合理选项",
                evidence=f"完赛 {n} 场",
            ))

    shallow_n = stats.get("shallow_samples") or 0
    shallow_pct = stats.get("shallow_home_win_pct")
    if shallow_n >= 2 and shallow_pct is not None:
        tone = "warn" if shallow_pct < 45 else "ok"
        cards.append(_card(
            card_id="shallow",
            title="亚盘偏浅",
            verdict="诱上风险" if shallow_pct < 45 else "主胜尚可",
            tone=tone,
            one_liner=f"偏浅 {shallow_n} 场，主胜仅 {shallow_pct}%",
            advice="欧赔看低主队但亚盘偏浅 → 优先考虑下盘或平局，防诱上",
            evidence="盘赔不一致（浅盘）",
        ))
        if shallow_pct < 45:
            actions.append("见「亚盘偏浅」标签时，慎追主队让球")

    deep_n = stats.get("deep_samples") or 0
    deep_pct = stats.get("deep_home_win_pct")
    if deep_n >= 2 and deep_pct is not None:
        cards.append(_card(
            card_id="deep",
            title="亚盘偏深",
            verdict="阻上/看低主" if deep_pct < 50 else "主队仍强",
            tone="neutral" if deep_pct < 50 else "ok",
            one_liner=f"偏深 {deep_n} 场，主胜 {deep_pct}%",
            advice="深盘不一定代表主队稳，也可能在阻上制造便宜假象",
            evidence="盘赔不一致（深盘）",
        ))

    aligned_n = stats.get("aligned_samples") or 0
    aligned_pct = stats.get("aligned_fav_hit_pct")
    if aligned_n >= 2 and aligned_pct is not None:
        tone = "ok" if aligned_pct >= 55 else "warn"
        cards.append(_card(
            card_id="aligned",
            title="盘赔一致",
            verdict="可跟" if aligned_pct >= 55 else "仍需谨慎",
            tone=tone,
            one_liner=f"一致盘 {aligned_n} 场，低赔打出 {aligned_pct}%",
            advice="盘赔同向时信号更清晰，但仍需控制仓位",
            evidence="欧赔与亚盘方向一致",
        ))

    line_up_n = stats.get("line_up_samples") or 0
    line_up_pct = stats.get("line_up_home_pct")
    if line_up_n >= 2 and line_up_pct is not None:
        cards.append(_card(
            card_id="line_up",
            title="临盘升盘",
            verdict="跟势" if line_up_pct >= 50 else "升盘陷阱",
            tone="ok" if line_up_pct >= 50 else "warn",
            one_liner=f"升盘 {line_up_n} 场，主胜 {line_up_pct}%",
            advice="升盘若配合低赔打出，可视为真实看好；反之防造热",
            evidence="初盘→临盘让球加深",
        ))

    line_down_n = stats.get("line_down_samples") or 0
    line_down_pct = stats.get("line_down_home_pct")
    if line_down_n >= 2 and line_down_pct is not None:
        cards.append(_card(
            card_id="line_down",
            title="临盘降盘",
            verdict="看衰主队" if line_down_pct < 45 else "降盘仍赢",
            tone="warn" if line_down_pct < 45 else "neutral",
            one_liner=f"降盘 {line_down_n} 场，主胜 {line_down_pct}%",
            advice="降盘多为主队信心不足信号，慎追上盘",
            evidence="初盘→临盘让球变浅",
        ))

    upsets = [u for u in upset_matches if u]
    if upsets:
        cards.append(_card(
            card_id="upsets",
            title="低赔爆冷",
            verdict=f"{len(upsets)} 场",
            tone="warn",
            one_liner="、".join(upsets[:3]) + ("…" if len(upsets) > 3 else ""),
            advice="强队/低赔翻车已发生，热门单场仓位宜轻",
            evidence="初赔 <2.0 的低赔项未打出",
        ))

    headline = _headline(cards, stats, n)
    if not actions:
        actions = [c["advice"] for c in cards[:3] if c.get("advice")]

    return {
        "headline": headline,
        "confidence": conf,
        "confidence_note": CONFIDENCE_NOTE[conf].replace("样本", f"{n} 场样本"),
        "actionable": _dedupe(actions)[:5],
        "cards": cards[:6],
    }


def _headline(cards: list[dict], stats: dict, n: int) -> str:
    if n == 0:
        return "暂无完场样本，开赛后自动归纳开盘套路"
    warns = [c for c in cards if c.get("tone") == "warn"]
    if warns:
        titles = "、".join(c["title"] for c in warns[:2])
        return f"本届开局：{titles}需重点防范"
    hr = stats.get("favorite_hit_rate_pct")
    if hr is not None and hr >= 58:
        return "本届初盘热门相对可靠，盘赔一致场次可优先参考"
    draw_r = stats.get("draw_rate_pct")
    if draw_r and draw_r >= 38:
        return "本届平局偏多，小组赛宜提高平局权重"
    return f"基于 {n} 场完赛：按盘赔结构单场研判，勿机械跟热门"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = x.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def match_takeaway(record: dict) -> str:
    """One-line conclusion for a finished match row."""
    actual = record.get("result_1x2")
    actual_cn = record.get("result_1x2_cn") or "—"
    fav = record.get("opening_favorite")
    fav_cn = record.get("opening_favorite_cn") or "—"
    cons = record.get("opening_consistency")
    cons_map = {"ah_shallow": "偏浅", "ah_deep": "偏深", "aligned": "一致"}
    cons_cn = cons_map.get(cons, "")

    if fav and fav != actual:
        tag = "冷门" if cons == "ah_shallow" else "低赔未出"
        return f"{tag} · 看{fav_cn}出{actual_cn}" + (f"（{cons_cn}）" if cons_cn else "")

    if cons_cn:
        return f"盘赔{cons_cn} · {actual_cn}"
    return actual_cn
