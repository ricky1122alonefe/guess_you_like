#!/usr/bin/env python3
"""Historical match stats + AI expert (DeepSeek/OpenAI) analysis and recommendation."""

from __future__ import annotations

import argparse
import json
import sys

from ai_prompt import (
    EXPERT_SYSTEM_PROMPT,
    LOCKED_SYSTEM_PROMPT,
    build_user_prompt,
    enrich_analysis_context,
    parse_analysis_json,
    parse_expert_json,
)
from deepseek_client import DeepSeekError, chat
from history import load_all_history
from jingcai_pick import attach_jingcai_recommendation
from parser import pair_match_files
from predict import build_payload
from analysis.rules import (
    apply_baseline_to_prediction,
    build_recommendation,
    merge_expert_prediction,
    print_ai_recommendation,
    print_batch_summary,
    recommendation_from_dict,
    recommendation_to_baseline,
)


def run_one_match(
    ah_xls: str,
    eu_xls: str,
    *,
    history,
    sample_limit: int,
    relaxed: bool,
    model: str,
    mode: str = "expert",
    base_url: str | None = None,
    api_key: str | None = None,
    provider_id: str = "deepseek",
    provider_label: str = "DeepSeek 精算师",
    poll_meta: dict | None = None,
    verbose: bool = True,
) -> tuple[dict, dict, dict]:
    payload = build_payload(
        ah_xls, eu_xls,
        sample_limit=sample_limit, relaxed=relaxed, history=history,
    )
    if poll_meta:
        payload["poll_meta"] = poll_meta
    rec = build_recommendation(payload)
    baseline = recommendation_to_baseline(rec)
    ctx = enrich_analysis_context(payload, baseline=baseline, mode=mode)

    system_prompt = EXPERT_SYSTEM_PROMPT if mode == "expert" else LOCKED_SYSTEM_PROMPT

    if verbose:
        from pipeline_output import (
            print_step_baseline,
            print_step_control,
            print_step_deepseek,
            print_step_files,
            print_step_match,
            print_step_odds,
            print_step_templates,
        )
        from parser import parse_match_pair

        current = parse_match_pair(ah_xls, eu_xls)
        print_step_files(ah_xls, eu_xls)
        print_step_odds(current)
        print_step_match(payload, current)
        print_step_baseline(rec, expert_mode=(mode == "expert"))
        print_step_control(ctx)
        print_step_templates(ctx)
        print_step_deepseek(rec.match, model, expert_mode=(mode == "expert"))
    else:
        o_ah = payload.get("open_stats", {}).get("count", 0)
        o_eu = payload.get("open_eu_stats", {}).get("count", 0)
        ah_n = payload["stats"].get("count", 0)
        eu_n = payload["eu_stats"].get("count", 0)
        label = f"{provider_label} EV 评估" if mode == "expert" else f"{provider_label} 论证"
        print(
            f"{rec.match}: 初盘 {o_ah}/{o_eu} | 临盘 {ah_n}/{eu_n} 场，{label}...",
            file=sys.stderr,
        )

    chat_kwargs: dict = {}
    if base_url:
        chat_kwargs["base_url"] = base_url
    if api_key:
        chat_kwargs["api_key"] = api_key

    content = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(payload, baseline, mode=mode)},
        ],
        model=model,
        temperature=0.2 if mode == "expert" else 0.1,
        max_tokens=4096,
        **chat_kwargs,
    )

    if mode == "expert":
        analysis = parse_expert_json(content)
        result = merge_expert_prediction(
            analysis, baseline, match_name=rec.match,
            evidence_brief=ctx.get("evidence_brief"),
        )
    else:
        analysis = parse_analysis_json(content)
        result = apply_baseline_to_prediction(
            analysis, baseline, match_name=rec.match,
            evidence_brief=ctx.get("evidence_brief"),
        )

    result["ai_provider"] = provider_id
    result["ai_provider_label"] = provider_label
    result["ai_model"] = model
    result["recommendation_source"] = f"ai_expert_{provider_id}"

    jc = (poll_meta or {}).get("jingcai")
    attach_jingcai_recommendation(result, jc)

    if verbose:
        from pipeline_output import print_step_final
        print_step_final(result)

    artifact = {
        "ah_xls": ah_xls,
        "eu_xls": eu_xls,
        "mode": mode,
        "payload": payload,
        "analysis_context": ctx,
        "reference_baseline": baseline,
        "ai_analysis_raw": analysis,
        "prediction": result,
    }
    return payload, result, artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI 精算师分析：历史样本 + 盘口数据 → EV 评估 + 投注建议。"
        " 默认 expert 模式（精算师独立研判）；--locked-baseline 为旧版论证模式。",
    )
    parser.add_argument(
        "xls_files",
        nargs="+",
        help="xls paths: 2 files (one match) or 4+ files (multiple matches)",
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--relaxed", action="store_true")
    parser.add_argument(
        "--model", default="deepseek-chat",
        help="模型名，DeepSeek 默认 deepseek-chat；OpenAI 可用 gpt-4o 等",
    )
    parser.add_argument(
        "--base-url",
        help="API 地址，默认 DeepSeek。OpenAI 示例: https://api.openai.com/v1",
    )
    parser.add_argument(
        "--locked-baseline",
        action="store_true",
        help="旧模式：规则引擎锁定结论，AI 只写论证（不推荐日常使用）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="只输出最终结论，跳过中间过程",
    )
    parser.add_argument("--json", action="store_true", help="output raw json")
    parser.add_argument("--save", help="save full pipeline to file (batch -> array)")
    args = parser.parse_args(argv)

    mode = "locked" if args.locked_baseline else "expert"

    try:
        pairs = pair_match_files(args.xls_files)
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print("正在加载历史库并匹配样本...", file=sys.stderr if args.quiet else sys.stdout)
    history = load_all_history()
    all_results = []
    recs = []

    for i, (ah_xls, eu_xls) in enumerate(pairs):
        if len(pairs) > 1:
            sep = f"\n{'#' * 60}\n  第 {i + 1}/{len(pairs)} 场\n{'#' * 60}\n"
            print(sep, file=sys.stderr if args.quiet else sys.stdout)
        try:
            payload, result, artifact = run_one_match(
                ah_xls, eu_xls,
                history=history,
                sample_limit=args.samples,
                relaxed=args.relaxed,
                model=args.model,
                mode=mode,
                base_url=args.base_url,
                verbose=not args.quiet and not args.json,
            )
        except DeepSeekError as exc:
            print(f"AI API 错误 ({ah_xls}): {exc}", file=sys.stderr)
            return 1
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"JSON 解析/校验失败: {exc}", file=sys.stderr)
            return 1

        all_results.append(artifact)
        recs.append(recommendation_from_dict(result))

        if args.json:
            continue
        if args.quiet:
            print_ai_recommendation(result)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            out = all_results[0] if len(all_results) == 1 else all_results
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    if args.json:
        out = all_results[0]["prediction"] if len(all_results) == 1 else [r["prediction"] for r in all_results]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif len(recs) > 1:
        print_batch_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
