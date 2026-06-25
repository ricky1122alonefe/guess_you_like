---
name: wc2026-knockout-outlook
description: >-
  Analyze 2026 World Cup group-stage qualification, best-third ranking, and
  R32 knockout paths using live standings. Use when predicting group outcomes,
  writing final-round copy, AI deep analysis, or explaining who a team may face
  in the round of 32.
---

# 2026 世界杯 · 出线签位与 32 强 outlook

## 何时使用

- 用户问某组谁已出线、谁必须抢分、德国类「已锁出线但末轮仍踢」
- 需要结合 **实时积分榜** 推演小组排名与 **32 强可能对手**
- 写末轮文案、AI 深度分析、定稿比对前的规则核对
- 解释 **12 个小组第三** 谁进前 8、谁出局

## 项目内数据源（优先读代码/JSON，勿臆造）

| 资源 | 路径 |
|------|------|
| 赛制与同分 | `data/wc2026_groups.json` |
| 32 强固定对阵 M73–M88 | `data/wc2026_knockout_bracket.json` |
| 规则 + AI prompt | `analysis/tournament/wc2026_tournament_rules.py` |
| 实时 outlook 报告 | `analysis/tournament/group_knockout_outlook.py` |
| 同分/情景推演 | `analysis/tournament/group_tiebreak.py` |
| 战意/锁定/签位 | `analysis/tournament/group_race.py` |

## API / 页面

- 全量报告：`GET /api/worldcup/groups/outlook?refresh=1`
- 可视化：`GET /worldcup/groups/outlook`
- 单场 AI 上下文：`outlook_for_match(match_name)` → 注入 `analysis_context.attach_tournament_context`

## 分析流程（必须遵守）

1. **拉最新数据**：`fetch_live_snapshot(force=True)` 或 outlook API；禁止用过期排名。
2. **组内排名**：FIFA Art.13 同分（相互战绩 mini-league → 全组 GD/GF → 公平竞赛 → FIFA 排名）。
3. **区分状态**：
   - `qualification_locked` / `locked_first` / `locked_top2` → 输赢与**是否出线**无关，仅影响**签位/轮换**
   - `must_win` → 必须抢分
   - `achievable_ranks` / `rank_scenarios` → 各排名下的 32 强路径
4. **最佳第三**：12 组第三横向比 **积分 → 净胜球 → 进球**（不比相互战绩）；前 8 进 32 强。
5. **32 强对阵**：
   - 组第一、组第二路径 **赛前固定**（见 bracket JSON）
   - 8 场「第一 vs 最佳第三」的第三来自 `third_pool`（如 1A 对 C/E/F/H/I 之一）
   - **Annex C 495 种组合**未入库时：**不得编造**精确第三对位，只能说「池内候选 + 全部 72 场赛后锁定」
6. **输出**：每个结论标注依据（积分上限、同分规则、当前 best_third 排名）。

## AI system prompt 片段

调用 `tournament_rules_system_prompt(compact=True)` 或完整版；用户 payload 中应含：

- `group_knockout_outlook` / `knockout_outlook`
- `best_third_live`
- `tournament_rules`

## 已知限制

- 定稿比对常用 1-0/1-1/0-1 推演，净胜球 tie 时仅供参考
- K/L 组第三路径最窄（仅 M88 / M80）
- 用户若提供 Annex C 表 → 可落库 `data/wc2026_annex_c_third_combinations.json` 后解锁精确第三对位

## 示例结论写法

> 德国已锁定 A 组前二，末轮输赢与出线无关，主要影响是否拿小组第一及 32 强对手（第一走 1A 签位 vs third_pool，第二走 2A 固定对阵）。同组 X 队必须取胜且依赖 Y 组赛果才能争最佳第三，当前第三排名第 9，不在进 32 强区。
