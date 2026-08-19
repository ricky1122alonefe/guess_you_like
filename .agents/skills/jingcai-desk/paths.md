# jingcai-desk · 相关路径

| 路径 | 作用 |
|------|------|
| `ai_prompt.py` | `EXPERT_SYSTEM_PROMPT`（盘口桌）；`PREMATCH_SYSTEM_PROMPT`（禁止搜网/读盘口） |
| `ai_schema.py` | `ACTUARY_JSON_KEYS`：含 `match_variables`、`judgment`、`judgment_condition` 等精算师输出 schema |
| `prematch_desk.py` | `build_prematch_desk` / `attach_prematch_and_summary` / `ensure_prematch_attached` / `build_comparison_summary` |
| `sporttery_intel.py` | 体彩官方伤停/停赛数据加载与抓取 |
| `match_agents/factor_fetch.py` | 赛前因子抓取：Open-Meteo 天气、球场坐标等 |
| `data/match_venues.json` | 球队/联赛默认球场与经纬度，供天气查询 |
| `analysis/team_form/club_form.py` | 俱乐部近期战绩与正赛日期，供赛程密度计算 |
| `web_ui.py` | `_comparison_summary_card`、`_prematch_detail_html`：详情页对照摘要与赛前桌展示 |
| `hourly_pipeline.py` | 批量预测流程中调用 `attach_prematch_and_summary(..., league_name=...)` 接线 |
| `serve.py` | 详情页路由，兜底调用 `ensure_prematch_attached` |
| `product_focus.py` | `focus_jingcai_only()`：竞彩过滤与北京时间 11:00 前回退逻辑 |
| `config.py` | `JINGCAI_RELEASE_HOUR = 11` 等竞彩开售时间配置 |
| `download_500.py` | `DownloadResult.league`：透传联赛名到 pipeline |
| `tests/test_prematch_desk.py` | 赛前桌、对照摘要、高影响规则测试 |
| `tests/test_ai_prompt.py` | 盘口桌 prompt 三层结构测试 |
| `tests/test_web_ui.py` | 详情页展示与对照摘要卡片测试 |
| `tests/test_pivot_jingcai.py` | 竞彩优先级过滤与时间回退测试 |
