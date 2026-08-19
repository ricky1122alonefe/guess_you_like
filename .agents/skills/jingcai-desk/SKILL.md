---
name: jingcai-desk
description: >
  竞彩开售联赛盘口工作台纪律与改码路由。两套产物隔离：盘口桌（SP/欧亚/同赔/战绩/EV→倾向/小注/放弃）
  与赛前桌（仅已核验伤停/天气/赛程；禁止赔率和投注方向）；对照摘要只能 hold/size_down/skip，禁止翻转主客。
  在改 guess_you_like 的 AI prompt、精算师桌、赛前桌、对照摘要、谁赢依据、prematch、actuary、jingcai、
  竞彩推荐、伤停，或用户想接入外部足球分析 skill/prompt 时使用。
---

# jingcai-desk · 竞彩盘口/赛前桌工作纪律

## 何时使用

- 用户要改 guess_you_like 的 AI 分析流程、盘口桌、赛前桌、对照摘要或相关 prompt。
- 用户提到「把伤停/天气/赛程放进 AI 结论」「接入外部足球分析 skill/prompt/长报告」。
- 用户想调整「谁赢·依据」卡片、详情页展示、精算师 JSON schema、竞彩推荐输出。
- 用户要求把泊松/同赔/Elo/亚盘/欧赔/SP 合并成单一结论或「这场会出 X」。

## 核心循环（必须遵守）

```
数学基准（泊松 / 同赔 / Elo / EV）
  → 已核验变数再研判（伤停 / 天气 / 赛程）
  → 判断仓位（倾向 / 小注 / 放弃）
```

泊松与同赔只输出「数学基准概率/赔率价值」，**不准写成「这场会出主胜/客胜/大球」**。

## 三套产物：绝对隔离

### 1. 盘口桌（odds / actuary desk）

- 只看：竞彩 SP、欧亚转换、分歧信号、同赔、战绩、EV。
- 输出：`judgment`、`judgment_condition`、`result_1x2_cn`、`recommendation`、仓位大小。
- **禁止**：编造伤停、天气、裁判、新闻、战意。这些信息不在本桌。
- 对应代码：`ai_prompt.py` 的 `EXPERT_SYSTEM_PROMPT`、`ai_schema.py` 的 `ACTUARY_JSON_KEYS`。

### 2. 赛前桌（prematch desk）

- 只看已核验事实：
  - 伤停/停赛：来自 `sporttery_intel.py`（体彩官方伤停 API）。
  - 天气：来自 `match_agents/factor_fetch.py` + `data/match_venues.json`（Open-Meteo）。
  - 赛程密度：来自 `analysis/team_form/club_form.py` 近期正赛日期。
- **禁止**：读取任何赔率、盘口、 implied probability、投注方向。
- **禁止**：输出 `result_1x2_cn`、`recommendation`、胜平负百分比。
- 无数据时维度标记为 `missing`，**禁止合理假设、推理补全**。
- 仅支持五大联赛（短名：英超/西甲/德甲/意甲/法甲；长名：英格兰超级联赛/西班牙甲级联赛/德国甲级联赛/意大利甲级联赛/法国甲级联赛）。日职、德乙、韩K 等返回 `available=false`。
- 对应代码：`prematch_desk.py` 的 `build_prematch_desk`、`attach_prematch_and_summary`、`ensure_prematch_attached`。

### 3. 对照摘要（comparison summary）

- **代码生成**，不是 LLM 输出。
- 动作只有三种：`hold`、`size_down`、`skip`。
- 赛前桌可以降仓或放弃，**禁止把主胜翻成客胜、大球翻成小球**。
- 对应代码：`prematch_desk.py` 的 `build_comparison_summary`；展示在 `web_ui.py` 的 `_comparison_summary_card`。

## `high_impact_facts` 准入白名单

只有以下已确认事实可进入 `high_impact_facts`：

1. 主力门将确认缺阵（伤病或官方缺阵）。
2. 球员明确停赛（`suspensionFlag=1` 或官方停赛名单）。
3. 极端天气：暴雨/大暴雨、风速 ≥ 40 km/h、气温 ≤ -10°C。

**以下不准进高影响**：普通伤员、出战成疑、阴天/小雨、德比战意、裁判风格、媒体消息、无官方来源的阵容。

## 禁止清单

- 禁止输出「必胜」「稳胆」「确定」「稳赢」。
- 禁止把竞彩让球、亚盘、欧赔、大小球当成同一种盘混用。
- 禁止把 DuckDuckGo / 500 有料 / 网络文章写入 `high_impact_facts`。
- 禁止用错误球场坐标拉天气；禁止用联赛默认球场代替球队真实主场。
- 禁止把外部足球长报告、阵型对位、球星分析接入竞彩购买结论。
- 禁止将盘口桌与赛前桌合并到同一次模型调用。

## 外部 football skill / GitHub 报告处理

- 可以借鉴其「盘口类型分清」「热度≠更稳」「无来源=missing」「先确认未完赛」等纪律。
- **不允许**把外部长报告、深度分析模板、阵型对位内容直接合并进 `ai_prompt.py` 的盘口桌 prompt。
- 用户要「球星破局/战术长报告」→ 单独输出，**不接**到竞彩购买结论。

## 代理改码路由决策树

| 用户意图 | 动哪里 | 不动哪里 |
|----------|--------|----------|
| 改方向 / EV / 精算师 JSON / 仓位语言 | 盘口桌 `ai_prompt.py` + `ai_schema.py` | 赛前桌、对照代码 |
| 改伤停/天气/赛程/降仓逻辑/高影响规则 | 赛前桌 `prematch_desk.py` + 数据源 | 盘口桌 prompt |
| 改详情页「谁赢·依据」/对照摘要展示 | `web_ui.py` | 泊松/同赔模型 |
| 用户丢来外部足球 skill/GitHub prompt | 拒绝合并；如需，只引用纪律，不拷模板 | 不要把长报告接入竞彩结论 |
| 用户要阵型/球星/战术长报告 | 单独生成文档/分析 | 不进入盘口桌结论 |

## 已知坑

- 详情页必须调用 `ensure_prematch_attached`，否则旧缓存没有 `comparison_summary`。
- `attach_prematch_and_summary` 必须带本场 `fixture_id` 与 `output_root`，否则伤停缓存找不到。
- `match_venues.json` 禁止把曼联/切尔西等映射到错误球场；禁止用联赛默认球场填天气。
- 时间相关测试在 11:00 前会触发「竞彩回退显示全部」逻辑，测试需 monkeypatch 到 14:00。

## 相关路径

详见同目录 [`paths.md`](paths.md)。
