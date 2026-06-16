"""Print full prediction pipeline: parse → match → baseline → AI → final."""

from __future__ import annotations

from parser import parse_match_pair
from predict import print_report
from recommend import print_ai_recommendation, print_recommendation


def _banner(title: str, step: int | None = None) -> None:
    line = "=" * 60
    print()
    print(line)
    if step is not None:
        print(f"  第 {step} 步 · {title}")
    else:
        print(f"  {title}")
    print(line)
    print()


def print_step_files(ah_xls: str, eu_xls: str, *, step: int = 1) -> None:
    _banner("解析球探 xls 盘口", step)
    print(f"  亚盘文件: {ah_xls}")
    print(f"  欧赔文件: {eu_xls}")


def print_step_odds(current) -> None:
    print("  ▎当前赛事")
    print(f"    比赛: {current.match_name}")
    print(f"    机构: {current.bookmaker}")
    print()
    print(
        f"    临盘亚盘: 上水 {current.ah_home_water} / 盘口 {current.ah_line} / "
        f"下水 {current.ah_away_water}"
    )
    if current.ah_open_line is not None:
        print(
            f"    初盘亚盘: 上水 {current.ah_open_home_water} / 盘口 {current.ah_open_line} / "
            f"下水 {current.ah_open_away_water}"
        )
    if current.eu_open_home:
        print(
            f"    初盘欧赔: 主 {current.eu_open_home} / 平 {current.eu_open_draw} / 客 {current.eu_open_away}"
        )
    print(
        f"    临盘欧赔: 主 {current.eu_home} / 平 {current.eu_draw} / 客 {current.eu_away}"
    )


def print_step_match(payload: dict, current, *, step: int = 2) -> None:
    _banner("历史样本匹配（初盘 + 临盘）", step)
    if payload.get("auto_relaxed"):
        print("  ⚠ 严格匹配无样本，已自动放宽条件重试")
        print()
    print(f"  历史库总量: {payload.get('history_total', 0)} 场")
    print()
    print_report(
        current,
        payload["stats"],
        payload["eu_stats"],
        payload.get("open_stats"),
        payload.get("open_eu_stats"),
    )


def print_step_baseline(rec, *, step: int = 3, expert_mode: bool = True) -> None:
    if expert_mode:
        _banner("规则引擎参考（量化模型，供 AI 专家对照）", step)
    else:
        _banner("规则引擎 baseline 推荐（最终结论以此为准）", step)
    print_recommendation(rec, title_suffix="规则引擎参考" if expert_mode else "规则引擎 baseline")


def print_step_control(ctx: dict, *, step: int = 4) -> None:
    _banner("机构控盘 / 规律权重解读", step)
    control = ctx.get("control_analysis") or {}
    pw = int((control.get("pattern_weight") or 1) * 100)
    print(f"  控盘强度: {control.get('level_cn', '—')}（{control.get('level', '—')}）")
    print(f"  变盘轨迹: {control.get('trajectory', '—')}")
    print(f"  规律参考价值: {pw}%")
    print(f"  赔付压力: {control.get('payout_pressure_note', '—')}")
    print()
    signals = ctx.get("market_signals") or {}
    if signals.get("line_summary"):
        print(f"  亚盘: {signals['line_summary']}")
    if signals.get("water_summary"):
        print(f"  水位: {signals['water_summary']}")
    if signals.get("eu_summary"):
        print(f"  欧赔: {signals['eu_summary']}")
    notes = control.get("notes") or signals.get("notes") or []
    if notes:
        print()
        print("  ▎风控要点")
        for n in notes:
            print(f"    · {n}")


def print_step_templates(ctx: dict, *, step: int = 5) -> None:
    _banner("AI 写作模板（程序预填，供 DeepSeek 套用）", step)
    templates = ctx.get("writing_templates") or {}
    for key, label in (
        ("historical_overview", "样本概览"),
        ("market_vs_history_analysis", "市场 vs 历史"),
        ("odds_movement_analysis", "盘赔走势"),
        ("asian_handicap_deep_dive", "亚盘深度"),
        ("score_pattern_analysis", "比分规律"),
        ("final_verdict_hint", "综合结论提示"),
        ("analysis_basis", "分析依据（预填，AI 须覆盖各层）"),
    ):
        val = templates.get(key)
        if not val:
            continue
        print(f"  ▎{label}")
        if isinstance(val, list):
            for line in val:
                print(f"    · {line}")
        else:
            print(f"    {val}")
        print()

    cases = ctx.get("required_historical_cases") or []
    if cases:
        print("  ▎锁定历史案例（AI 不得自造）")
        for i, c in enumerate(cases, 1):
            print(f"    {i}. [{c.get('date')}] {c.get('match')} → {c.get('result')}")
            if c.get("lesson_template"):
                print(f"       {c['lesson_template']}")
        print()

    brief = ctx.get("evidence_brief") or {}
    if brief.get("layers"):
        print("  ▎分析依据层级（evidence_brief，AI 须逐层输出）")
        for layer in brief["layers"]:
            print(f"    · [{layer.get('title')}] {layer.get('text')}")
        print()

    risks = ctx.get("suggested_risks") or []
    if risks:
        print("  ▎建议风险点（选 2 条）")
        for r in risks:
            print(f"    · {r}")


def print_step_deepseek(match: str, model: str, *, step: int = 6, expert_mode: bool = True) -> None:
    if expert_mode:
        _banner("调用 AI 专家（精算师模式：独立分析与推荐）", step)
        print(f"  赛事: {match}")
        print(f"  模型: {model}")
        print("  说明: AI 综合历史样本+盘口数据，输出最终推荐与分析依据")
    else:
        _banner("调用 DeepSeek 生成分析文字", step)
        print(f"  赛事: {match}")
        print(f"  模型: {model}")
        print("  说明: 推荐结论已锁定，AI 只写分析论证，不修改 baseline")


def print_step_final(result: dict, *, step: int = 7) -> None:
    _banner("最终输出（baseline + DeepSeek 分析）", step)
    print_ai_recommendation(result)


def print_full_pipeline(
    *,
    ah_xls: str,
    eu_xls: str,
    payload: dict,
    rec,
    ctx: dict,
    result: dict,
    model: str,
) -> None:
    """Print all pipeline steps then final merged output."""
    current = parse_match_pair(ah_xls, eu_xls)
    print_step_files(ah_xls, eu_xls)
    print_step_odds(current)
    print_step_match(payload, current)
    print_step_baseline(rec)
    print_step_control(ctx)
    print_step_templates(ctx)
    print_step_deepseek(rec.match, model)
    print_step_final(result)
