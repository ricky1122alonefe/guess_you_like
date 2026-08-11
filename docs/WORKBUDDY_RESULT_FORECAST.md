# WorkBuddy 指令：结果预测（必发 + 欧赔 + 亚盘 + 历史 + 近期战绩）

> **角色**  
> - **指令方 / 规划**：只定目标与验收，不代写业务代码（本文件）。  
> - **实现方（WorkBuddy）**：只在 **`guess_you_like`** 改代码。  
> - **禁止**：再改 `fussball-bund` 当产品；禁止开新仓库。  
>  
> **用户目标（一句话）**  
> 用 **必发 + 欧洲赔率 + 亚洲盘口 + 历史战绩 + 近期战绩**，在 gyl 里产出 **可展示的 1X2 结果预测**（主/平/客 + 置信说明），不是再做世界杯专题页。

---

## 0. 产品定义（照此验收，勿跑偏）

### 输入（每场必须尽量凑齐）

| # | 信号 | 含义 | 仓库内已有抓取/模块（优先复用） |
|---|------|------|----------------------------------|
| 1 | **必发** | 成交量/价、热度/资金方向 | `betfair_500.py`，poll tick 里的必发字段 / UI 必发图 |
| 2 | **欧洲赔率** | 1X2 初盘/即盘、隐含概率 | `poll_500` 欧赔、`eu_odds_chart`、`eu_implied_metrics`、欧盘 xls |
| 3 | **亚洲盘口** | 盘口线 + 水、升降水 | 亚盘 xls / poll 亚盘、`ah.py`、`ah_analytics` |
| 4 | **历史战绩** | 同类盘口/赔率历史相似样本及赛果分布 | `history.py`、`match.py`（`find_similar`）、`predict.py` + football-data |
| 5 | **近期战绩** | 近 N 场胜平负/进失球 | `team_recent_form.py`、`team_form_search.py`（国足向）；联赛队需补齐或扩源 |

### 输出（标准化，写入 prediction 结构）

每场必须产出统一结构（字段名可微调，但语义固定）：

```text
result_prediction:
  pick: home | draw | away | skip
  pick_cn: 主胜 | 平 | 客胜 | 观望
  p_home, p_draw, p_away: float 0~1  （模型/融合概率，和为 1）
  confidence: high | mid | low
  reasons: []     # 中文要点，每条对应某一类信号（必发/欧/亚/历史/战绩）
  factors: {      # 可追溯
    betfair: {...},
    european: {...},
    asian: {...},
    history_similar: {...},
    recent_form: {...}
  }
  missing: []     # 哪些信号缺失，缺失时如何降权
```

**展示位置（硬性）**：

1. 单场详情 `/match/{fid}` 显眼区：**「结果预测」**（主/平/客 + 概率条 + 理由 3～5 条）  
2. 首页/当日列表：可加一列「预测」或图标；无数据则「—」  
3. 无 LLM 也必须能给出规则融合结果；AI 仅润色/复核（可选，非 blockers）

**非目标（本迭代不做）**：

- 自动购彩 / 竞彩 SP 当唯一预测源（SP 可作对照，**不得替代**上述五源融合）  
- 重做 bund、写大部头 RESEARCH  
- 保证命中率宣传  

---

## 1. 现状认知（WorkBuddy 先读再写）

仓库里 **不是从零**：

| 链路 | 文件 | 做什么 |
|------|------|--------|
| 规则推荐主链 | `predict.py` → `match.py` 相似样本 → `recommend` / `analysis/rules/engine.py` | 欧亚历史相似 → 1X2 推荐 |
| Poll 实时盘 | `poll_service` → `poll_500` | 写库欧/亚/竞彩/必发快照 |
| 量化 | `analysis/quant/*`、`analysis/pipeline.py` enrich | Dixon-Coles/Elo 等 attach |
| AI 预测 | `predict_ai.py`、`analysis/ai/*`、`hourly_pipeline` | 可能已生成 predict_row，但不保证五源齐 |

**问题（用户体感「乱 / 没有过程」）**：

- 信号分散在详情各卡片，**没有「五源 → 一句结果预测」的统一出口**  
- 首页像盘口表，预测结论不突出  
- 近期战绩多偏国际队/世界杯数据源，**联赛场可能空** — 需写清降级策略  

---

## 2. 实现任务包（按顺序，一个 PR 可含 T1–T3）

### T0 — 对齐（0.5 天，必做）

```text
【T0】摸清数据落点

1. 用 1 场已 poll 的 fixture_id，在 Postgres / match timeline 里找到：
   - 欧赔 主平客 初/即
   - 亚盘 盘口与水
   - 必发 是否有字段、空时原因
2. 对同一场跑一次现有规则预测（predict / hourly 入口，以仓库实际 CLI 为准）
3. 输出备忘：五源「有/无/缺口」表，贴在 PR 描述

验收：PR 描述含该表，不开始大重构。
```

### T1 — 组装「预测上下文」对象（1–2 天）【核心】

```text
【T1】Feature bundle：单场五源上下文

目标模块（建议新文件，避免再塞满 web_ui）：
  analysis/result_forecast/context.py
  或 services/result_forecast.py

函数示例（名字可改）：
  build_result_forecast_context(fixture_id | match_index + poll_meta + paths) -> dict
返回含：
  - european: 当前/初盘 1X2、去水概率、热门项、升降水摘要
  - asian: 当前盘线、主客水、相对初盘变化
  - betfair: 成交、back/lay 或页面已有结构；无则 missing.append("betfair")
  - history_similar: 复用 find_similar / payload 相似 TopN 的 1X2 分布（p_home/draw/away）
  - recent_form: 主客近 5～10 场战绩摘要（胜平负串、得失球）；无则 missing

约束：
- 禁止 sys.path 指到 fussball-bund
- 优先读 poll DB / 已有 timeline，避免每点详情再打爆 500（可选缓存 5–15 分钟）
- 缺源不抛死错，进 missing

验收：
  pytest 用 mock 场次：五源齐全 / 缺必发 / 缺战绩 三种 dict 可序列化
```

### T2 — 规则融合「结果预测」引擎（1–2 天）【核心】

```text
【T2】融合为 result_prediction

建议：analysis/result_forecast/engine.py

融合原则（写死、可配置权重，默认如下，后续可调）：

1. 历史相似 1X2 分布         权重基线 0.35
2. 欧赔去水隐含概率           权重基线 0.25
3. 亚盘方向（上盘热/降水）   权重基线 0.15  （映射到主/客倾向，平局弱）
4. 必发热度与价差             权重基线 0.15  （顺资金微调；与欧冷热背离则降权或标风险）
5. 近期战绩（主客近况差）     权重基线 0.10

规则：
- 权重在 missing 源上按比例重分配到「仍有」的源
- pick = argmax(p_home,p_draw,p_away)；max(p) < 0.38 → pick=skip 观望
- 欧亚严重分歧 / 必发与欧盘严重背离 → confidence 降级或 skip（参考现有 eu_ah_divergence、trap 逻辑可复用思路）
- reasons[]：每个进入融合的源至少 1 条中文短句（数据说话，禁止空话）

输出：attach 到现有 pred dict：
  pred["result_prediction"] = {...}

入口（任选其一体现在产品上，须至少一条在线路径）：
  A) hourly_pipeline / 预测生成后立即 T2
  B) 详情页 on-demand：无缓存则现场 build+fuse，写 archive
  C) CLI：`guess-you-like forecast --fid XXX`（可选但利于调试）

验收：
  单元测试：给定固定 factors → 固定 pick / skip
  手动：1 个真实 fid 控制台打印 p_* 与 reasons
```

### T3 — UI 展示「结果预测」（1 天）

```text
【T3】页面露出

1. /match/{fid} 顶部或推荐区上方：结果预测卡片
   - 大号：主胜/平/客 或 观望
   - 三概率条
   - reasons 列表
   - missing 灰字提示「缺必发：已降权」
2. 首页表格：列「预测」= pick_cn 或 —
3. 不要把世界杯盘路逻辑绑进这张卡

验收：截图 + 无 AI key 也能出卡（纯规则）
```

### T4 — 近期战绩补洞（1～2 天，按 T0 结果决定）

```text
【T4】仅当 T0 显示联赛队 recent_form 经常空

- 复用/扩展 team_recent_form 或 football-data / 500 积分/近期页面
- 输出统一：last_5 = WDLWD，goals_for/against
- 联赛名映射失败 → missing，不把错误队名硬套

验收：英超/主流联赛 1 场有近期串；冷门联赛允许 missing
```

### T5 — 可选 AI 包装（P2，勿阻塞）

```text
【T5】LLM 只吃 result_prediction.factors + reasons
禁止 AI 在缺少欧亚数据时胡编比分当主结论
主结论永远是 T2 规则 pick；AI 副标题「补充说明」
```

---

## 3. 质量与测试

```bash
cd guess_you_like
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/test_smoke.py -q -k "predict or forecast or recommend"  # 按新测例名调整
# 新增 tests/test_result_forecast.py 覆盖 T1/T2
```

- 外网 poll 可人工；CI 只跑 mock  
- 不删现有世界杯页面，但新预测 **不依赖** 世界杯数据才显示  

---

## 4. 给 WorkBuddy 的约束清单

1. **只改 gyl**  
2. **五源进、一预测出**；禁止只显示竞彩 SP 当「结果预测」  
3. **可解释**：页面必须 reasons + missing  
4. **缺数据降级，不崩溃**  
5. **少动 web_ui 巨型逻辑**：新逻辑进 `analysis/result_forecast/`，UI 只渲染  
6. 权重数值写 `config.py` 或 `data/result_forecast_weights.json`，勿魔法数散落  
7. PR 描述包含：T0 信号表 + 1 场手动结果  

---

## 5. 验收清单（产品）

- [ ] 随机抽 3 场已有欧亚盘的比赛，详情页均有「结果预测」  
- [ ] 至少 1 场能同时显示：欧 + 亚 + 历史相似 参与 reasons  
- [ ] 必发缺失时仍有预测，并标注 missing  
- [ ] 概率和 ≈ 1，观望阈值符合配置  
- [ ] 预测与「竞彩推荐」可并存，但文案区分：**赛果预测** vs **竞彩可购**  

---

## 6. 直接复制给 WorkBuddy 的开工摘要

```text
【项目】guess_you_like
【目标】必发 + 欧赔 + 亚盘 + 历史相似战绩 + 近期战绩 → 统一「结果预测」(1X2)
【别碰】fussball-bund；别把竞彩 SP 当唯一预测
【顺序】T0 数据摸底 → T1 build_context → T2 fuse engine → T3 详情/列表 UI → T4 战绩补洞 → T5 AI可选
【复用】betfair_500, poll 欧亚, predict/match 相似样本, analysis/rules, team_recent_form, eu_ah_divergence 思路
【新建】analysis/result_forecast/{context,engine}.py + tests/test_result_forecast.py
【验收】详情页结果预测卡片可解释；无 AI 也能出结果
【文档】docs/PRODUCT_SCOPE.md 可补一行主能力，但以本指令为准
```

---

## 7. 成功标准（一句话）

> 用户打开任意有欧亚盘的单场，**不用懂底层模块**，也能看到基于 **必发/欧/亚/历史/近况** 融合出的 **主/平/客（或观望）+ 概率 + 分项理由**。

---

## 8. UI 收口（A 部分，与 B 同 PR）

### 导航 `_page_nav`
- 主链：首页 · 当日推荐 · 复盘
- 折叠「更多 ▾」：世界杯 / 淘汰赛 / 亚盘赢盘 / 欧亚分歧 / 量化回测 / Kelly / AI 设置 / Agent 工作流

### 首页 `html_dashboard`
- 标题：竞彩盘口 · 赛果预测
- 状态行：运行中/空闲 · 库内 N 场
- 主表列：选 | 比赛 | 推荐(竞彩+SP) | 亚盘 | 置信 | 详情
- 删除：档位列、比分列、Agent研判列、AI列、甜区筛选、导出PNG、批量海报、模型select、AI自动2串1
- 删除：世界杯/欧亚分歧/甜区 teaser、AI 聊天卡片
- 完场表列：比赛 | 赛果 | 预测 | 命中 | 详情

### 单场 `html_match_detail`
- 顶部按钮：返回 + AI推荐本场 + 快照数（其余进「更多操作」折叠）
- 首屏顺序：结果预测卡 → 规则推荐卡 → 盘口信号区（竞彩+欧赔+必发）
- 折叠：更多操作、Agent 分析、策略&甜区&量化、走势图、相似样本、变动、Poll明细

### 当日页 `html_daily_picks`
- 用 `_page_nav(back=True)` 替代硬编码导航
- 去掉 AI 聊天块（保留「AI 分析当日」按钮）

### 测试适配
- `test_dashboard_chief_report_column`: 断言 "推荐"（不再断言 "Agent研判"）
- `test_match_agents_board_and_guardrail_render`: Agent 内容在折叠区，仍可断言
