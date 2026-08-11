# CodeBuddy 指令：产品收敛 — 盘口 + 战绩 + 去水 + 串关 EV + 精简 AI

> **执行方**：CodeBuddy（改代码）  
> **仓库**：仅 `guess_you_like`  
> **禁止**：改 fussball-bund；无限堆 Agent/世界杯入口  
> **日期**：2026-08-11  
> **取代**：以「竞彩满页 + 多 Agent 墙」为主叙事的旧验收；世界杯/FIFA 等标 legacy。

---

## 0. 用户定调（产品一句话）

做 **盘口研究工作台**，不是功能堆叠站：

| 要 | 不要 |
|----|------|
| 欧赔、亚盘、欧亚分歧、必发成交/指数 | 满屏无用按钮与世界杯/Agent/量化墙 |
| 近 20～50 场战绩总结 + **主队近 20 主场 / 客队近 20 客场**（带对应赔率） | 空壳「五源缺失」吓人文案当分析 |
| **去水隐含概率**（隐藏概率）写进卡片与 AI 输入 | 只展示毛赔、不说抽水 |
| 勾选 **2～3 场** 算 **组合 EV** | 只有串关分析无 EV |
| 上述结构化结果 **喂 AI** 出一段可读分析 | AI 空话 / 必须先点十个按钮 |

**核心数据是否够？** — **够。**  
盘口侧：**欧赔 + 亚盘 + 欧亚分歧 + 必发** +（有则）竞彩 SP 作「可购对照」。  
球队侧：**近 20～50 综合 + 近 20 主/客专用 + 当时/收盘赔率**。  
叠加 **去水概率 + 串关 EV + AI 解释** = 产品完整闭环。  
**不必** 再堆：FIFA 预览、多 Agent 流水线墙、凯利百科、世界杯小组路径 作主路径。

---

## 1. 目标架构（交付心智）

```text
poll(500 欧/亚/必发/竞彩 SP)
    ↓
单场 context bundle（结构化）
  · market: eu, ah, betfair, divergence, devig(p_h,p_d,p_a)
  · form: last_20_50 summary, home_home_20, away_away_20 + odds tags
    ↓
规则层：1X2 倾向 / 观望 / 分歧提示
    ↓
UI 清爽：三块卡 + 串关 EV
    ↓
AI：只吃 bundle JSON，输出中文短报（可选）
```

---

## 2. 分阶段任务（按序）

### P0 — 页面减法（1～2 天）【先做，体感立刻】

**文件**：`web_ui.py` / 必要 CSS

**首页 `/`**

- 主表列：**选 | 比赛 | 欧去水/倾向 | 亚盘 | 必发热 | 规则倾向 | 详情**
- 工具条只留：刷新 poll/分析、勾选 2～3 场 → **算串关 EV**
- 导航主链：**首页 · 复盘**；其余进「更多」（世界杯/quant/Agent 设置/Kelly…）
- 删除或默认隐藏：甜区墙、海报批打、首页 AI 聊天大卡、多 Agent 入口

**单场 `/match/{fid}` 首屏只允许 4 块（顺序固定）**

1. **盘口**（欧赔去水条 + 亚盘 + 必发 + 欧亚分歧一句话）  
2. **战绩**（20/50 总结 + 主 20 主场 / 客 20 客场表摘要）  
3. **规则结论**（倾向 主/平/客/观望 + 理由 3～5 条）  
4. **AI 分析**（有 key 显示；无 key 显示「规则结论即可用」）  

其余全部 `<details>` 默认折叠：Agent、深度、FIFA、存图长页、poll 明细……

**验收**：窄屏首屏看不到 Agent / 世界杯；盘口+战绩+结论一眼可见。

---

### P1 — 去水隐含概率（统一 API）（0.5～1 天）

**新模块建议**：`analysis/market/devig.py`（或扩现有 `eu_implied_metrics` / `result_forecast`）

```text
def devig_1x2(odds_h, odds_d, odds_a, method="proportional") -> {
  "p_home","p_draw","p_away",  # sum=1
  "overround",                 # 毛抽水
  "fair_odds": {...}           # 可选
}
```

- 默认 proportional：`p_i ∝ 1/o_i` 再归一  
- **所有**结果预测、串关 EV、AI payload 必须用 **devig 后 p_***，禁止只用 1/odds 不归一  
- UI 文案统一叫：**「隐含概率（去水）」**，旁注抽水 %

**验收**：单测 2.0/3.2/3.8 → p 和=1、overround>0；卡片展示 % 与抽水。

---

### P2 — 战绩引擎：20～50 + 主客专向 + 赔率（2～3 天）【核心新增】

**新模块建议**：`analysis/team_form/club_form.py`（勿再死绑世界杯 Excel）

**输入**：主队名、客队名、联赛（500 展示名）、kickoff  

**数据源优先级**（能实现再加，至少 1 条通路）：

1. 本仓 `data/leagues/*.csv`（football-data）队名模糊匹配  
2. 已有 history 管线 / openfootball  
3. 失败 → `missing` + 文案「联赛历史未匹配」，**不阻断**盘口分析  

**输出结构（固定，挂 pred 或独立 API）**：

```json
{
  "window_n": 30,
  "overall": {
    "home_team": {"played":30,"w":..,"d":..,"l":..,"gf":..,"ga":..,"pts":..,
                  "summary_cn":"…近30场…"},
    "away_team": { ... }
  },
  "split": {
    "home_at_home_last_20": {
      "played":20,"w":..,"d":..,"l":..,"gf":..,"ga":..,
      "avg_eu_home": null, "avg_ah_line": null,
      "samples": [{"date","opp","score","result","eu_h","eu_d","eu_a","ah_line"}]
    },
    "away_at_away_last_20": { ... 同上 ... }
  },
  "h2h_optional": {}
}
```

规则：

- overall 窗口可配置 20|30|50（默认 30，UI 可切换）  
- split **硬要求至少尝试 20 场**；不足则 `played < 20` 标明样本不足  
- samples 尽量带 **当时欧赔/亚盘**（CSV 有 B365/PS 等列则填）；无赔率则 null，仍可要战绩  
- UI 战绩卡：两队总览一行 + 主场/客场两表（最多展示近 5 行 + 「展开全部」）

**验收**：英超知名队能出 20+ 主场行；冷门队 missing 不崩。

---

### P3 — 欧亚分歧 + 必发 进主结论（1 天）

复用：

- `eu_ah_divergence` / signals  
- poll 的 betfair  

并入 **规则结论 reasons**（必须中文短句）：

- 欧主热 vs 亚盘让球方向  
- 必发成交占比 vs 欧赔隐含  

仍缺必发：reason 写「无必发成交」降置信，**不**整卡报废。

---

### P4 — 串关 2～3 场 EV（1～2 天）【你点名的功能】

**入口**：首页勾选 2 或 3 场 → 按钮「计算串关 EV」

**输入每腿**：

- 用户选向或默认规则 1X2 pick  
- 结算赔率优先级：竞彩 SP 若可购 > 否则欧赔对应项  
- 模型概率：该场 **devig 后 p_pick**（或规则融合 p）

**公式（写死文档）**：

```text
单腿 EV = p_model * odds - 1
串关 p_parlay = Π p_i   （默认独立假设；UI 注明）
串关 odds_parlay = Π odds_i
串关 EV = p_parlay * odds_parlay - 1
```

**输出 UI 卡**：

- 每腿：方向 / odds / p / 单腿 EV  
- 组合：组合赔 / 组合 p / **组合 EV** / 金额示例（可选 stake 输入）  
- EV>0 与 <0 颜色区分；**不承诺赚钱** 免责  

复用/改造：`custom_parlay.py`、前端已有勾选 → 扩展返回 `ev` 字段。

**验收**：勾 2 场 mock → JSON/HTML 有 ev、parlay_ev；3 场同理；1 场禁用按钮。

---

### P5 — AI 只吃打包上下文（1 天）

**禁止** 让 AI 自行「脑补」无盘口场。

**POST 分析组装 `ai_match_brief_payload`**：

```json
{
  "match": "...",
  "market": { "eu":..., "ah":..., "devig":..., "divergence":..., "betfair":... },
  "form": { ... P2 结构 ... },
  "rule_conclusion": { "pick","reasons","p_devig":... },
  "missing": []
}
```

Prompt 大纲：

1. 先复述去水概率与抽水  
2. 结合主场/客场 20 样本与盘口是否同向  
3. 分歧/必发是否预警  
4. 明确：主/平/客或观望 + 风险一句  
5. 不提竞彩购买指令也可；有 SP 再单独「可购参考」  

无 API key：只展示规则结论 + 「一键复制给外部 AI」文本框（payload markdown）。

---

### P6 — 清理与配置（并行）

- `config.py`：`FORM_WINDOW_DEFAULT=30`，`FORM_SPLIT_N=20`，`PARLAY_MAX_LEGS=3`  
- README / `docs/PRODUCT_SCOPE.md` 改成上述主路径  
- 旧页路由保留但不进主导航  

---

## 3. 验收清单（产品）

- [ ] 首页无 Agent/世界杯墙；勾 2–3 场出 **组合 EV**  
- [ ] 单场首屏四块：盘口（含去水）/ 战绩 20–50+主客20 / 规则 / AI  
- [ ] 隐含概率和 = 1，显示抽水 %  
- [ ] 主队主场≤20、客队客场≤20 有表或明确样本不足  
- [ ] AI 输入可追溯到 payload（日志或 debug 折叠）  
- [ ] 无竞彩仍可完成「赛果盘口分析」  
- [ ] pytest：devig、form mock、parlay EV 单测绿  

---

## 4. 开工摘要（直接复制给 CodeBuddy）

```text
【仓】guess_you_like
【产品】盘口工作台：欧赔+亚盘+欧亚分歧+必发 + 战绩20/50与主20客20(含赔率) + 去水概率 + 2～3场串关EV + 结构化喂AI
【减】首页/单场砍掉无用入口；世界杯/Agent 进更多或折叠
【序】P0 UI减法 → P1 devig统一 → P2 俱乐部战绩引擎 → P3 分歧必发进结论 → P4 串关EV → P5 AI payload → P6 文档配置
【验】见 docs/CODEBUDDY_MARKET_FORM_EV.md §3
【禁】bund；保证盈利文案；把竞彩空当成无法分析
```

---

## 5. 与现状关系（给 CodeBuddy 避坑）

| 已有 | 用法 |
|------|------|
| poll 欧/亚/必发/竞彩 | 主数据源，修空 tick 问题继续有效 |
| result_forecast | 收敛为规则结论层，权重以 devig 欧亚+分歧+战绩为主 |
| eu_ah_divergence | 并入盘口卡 + reasons |
| custom_parlay / 首页勾选 | 加 EV 字段与 2～3 限制 |
| team_recent_form | 国足向；俱乐部走新 club_form |
| 世界杯/Agent UI | 不删库也可，**首屏不出现** |

---

## 6. 成功标准（一句话）

> 用户选场看盘（去水）、看近 20 主客战绩与赔率、看分歧/必发，勾 2～3 场得串关 EV，点 AI 得到基于同一数据包的分析——页面除此之外默认静音。
