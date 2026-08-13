# 爬虫准确性门禁（Scraper Accuracy Gate）

## 目标
确保 `guess_you_like` 所有 poll 相关爬虫「抓对、合对、写对」：字段语义不串、队名不脏、盘口变动正确落库、odds_latest 与最新 tick 一致。

## 字段语义

| 字段 | 含义 | 合法范围 | 备注 |
|------|------|----------|------|
| `eu_home/draw/away` | 欧赔即时三向 | 1.01–80.0 | 三向要么全合法、要么全空；禁止亚水串入 |
| `eu_open_*` | 庄家初盘（页内） | 1.01–80.0 | `<1.30` 且亚盘水同级时标 warning「疑似串水」，不用于观测初盘 |
| `ah_line` | 亚盘盘口 | 数值 handicap | 主队视角；负值=主让 |
| `ah_home/away_water` | 亚盘水位 | 0.30–3.50 | 有 line 时双水必须同时合法 |
| `ou_line/over/under` | 大小球 | line 1.0–6.5，水 0.30–3.50 | 只进 `raw_meta.ou` + 约定列 |
| `raw_meta.jingcai` | 竞彩 SP / RQSP | `has_sp` 为 true 时 `sp_*` 可解析 | 有 `match_num` 时建议有 jingcai 结构 |
| `raw_meta.betfair` | 必发量/价/占比 | `has_data` 为 true 时 `volume_total>0` | 0 成交时不虚构热门方向 |

## tick_hash 包含键
`tick_hash` 用于判断「有变动才写 tick」，包含：
- 欧亚 OU 全部关键字段：`bookmaker`, `ah_line`, `ah_home_water`, `ah_away_water`, `ah_open_*`, `eu_home`, `eu_draw`, `eu_away`, `eu_open_*`, `ou_line`, `ou_over`, `ou_under`, `ou_open_*`
- `eu_books_fp`：百家欧赔指纹
- `jingcai`：match_num / has_sp / sp_* / has_rqsp / rqsp_* / handicap / has_score_market
- `betfair`：volume_home/draw/away/total / volume_pct

因此仅竞彩 SP 或仅必发量变动也会生成新 tick，避免时间线僵住。

## 如何跑审计

```bash
# 人读摘要
python -m scripts.scraper_accuracy_audit --hours 48

# JSON 输出
python -m scripts.scraper_accuracy_audit --hours 48 --json

# 含现场重抓样本（需网络；无网则 skip）
python -m scripts.scraper_accuracy_audit --hours 48 --live-sample 3
```

退出码：存在 P0 error（非法欧亚、latest/tick 不一致、脏队名）→ `exit 1`；仅 warning → `exit 0`。

## 如何解读「欧粘亚动」

500.com 欧赔经常粘滞（多场欧赔不变），但亚盘水位、竞彩 SP、必发量仍在动。审计会统计：

```
欧粘亚动占比: N/M = X%
```

- 占比高 ≠ 爬虫坏了，而是数据源特性。
- 占比长期为 0 且 tick 数正常，需检查解析是否把亚水/SP 变动漏掉了。

## P0 / P1 / P2 定义

- **P0**：会写进库的错误映射（欧亚串字段、脏队名、空壳 tick 入库、odds_latest 与 tick 不一致）
- **P1**：jingcai/betfair 结构缺失但源页明明有（解析漏）
- **P2**：kickoff 缺失、ou 覆盖率低（warn + 能修则修）

## 当前状态示例（需以实际审计输出为准）

```
检查窗口: 近 48 小时
检查 ticks: 1269
  P0 error 数: 0
  warning 数: 217
脏队名/空队名场数: 0
odds_latest 与最新 tick 不一致: 0 / 30
raw_meta 缺失率: 竞彩=0.0% 必发=0.0% OU=64.0%
欧粘亚动占比: 0/17 = 0.0%
poll_500_last_run: 2026-08-13 10:46:49 | errors=0
```

## 质量门接入 poll 主链

`poll_service.run_once` 中 `poll_fixture` 返回 tick 后，已由 `assert_tick_has_markets` 校验欧亚非空。若需更强校验，可在 `insert_tick_if_changed` 前调用 `scripts.scraper_accuracy_audit._validate_tick`，将 `error` 级问题写入 `summary.errors` 并跳过入库。
