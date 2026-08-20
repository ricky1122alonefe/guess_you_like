# jingcai-desk · 相关路径

| 路径 | 作用 |
|------|------|
| `poll_service.py` | 500.com 欧亚轮询入口；与竞彩开售无关；CLI 含 `--interval` / `--interval-pre-jingcai` |
| `poll_interval.py` | `poll_interval_seconds(default=300, pre_jingcai=120)`：按北京时间 11 点自适应轮询间隔 |
| `poll_500.py` | `poll_fixture` 抓 `ouzhi-{fid}` / `yazhi-{fid}`；`raw_meta` 含 `eu_books` 与 `eu_books_major` |
| `eu_odds_chart.py` | `select_major_eu_books`：从 500 欧赔表挑出主要欧洲公司（兼容打码庄名，如 `威***威***(英国)`→威廉） |
| `jingcai_pick.py` | `compute_jingcai_pick`：竞彩 SP/RQSP 唯一可购结论 |
| `analysis/market/devig.py` | `devig_1x2`：欧赔去水隐含概率 |
| `analysis/market/three_lane.py` | `build_eu_lane` / `build_ah_lane` / `build_jingcai_lane` / `build_lane_comparison` / `attach_market_lanes`：三轨盘口；`eu_books_major` 优先于欧赔均值 |
| `ai_prompt.py` | `EXPERT_SYSTEM_PROMPT`（盘口桌）；`PREMATCH_SYSTEM_PROMPT`（禁止搜网/读盘口）；`actuary_input` 含三轨摘要只读块 |
| `ai_schema.py` | `ACTUARY_JSON_KEYS`：含 `match_variables`、`judgment`、`judgment_condition` 等精算师输出 schema |
| `prematch_desk.py` | `build_prematch_desk` / `attach_prematch_and_summary` / `ensure_prematch_attached` / `build_comparison_summary` |
| `sporttery_intel.py` | 体彩官方伤停/停赛数据加载与抓取 |
| `match_agents/factor_fetch.py` | 赛前因子抓取：Open-Meteo 天气、球场坐标等；天气只认主队/球场对得上的映射 |
| `data/match_venues.json` | 球队默认球场与经纬度；联赛兜底（`competition_default_venue`）不再用于天气 |
| `analysis/team_form/club_form.py` | 俱乐部近期战绩与正赛日期，供赛程密度计算 |
| `web_ui.py` | `_market_lanes_card`、`_comparison_summary_card`、`_prematch_detail_html`：详情页三轨盘口、对照摘要与赛前桌展示 |
| `hourly_pipeline.py` | 批量预测流程中调用 `attach_prematch_and_summary` / `attach_market_lanes(..., fixture_id=..., output_root=...)` 接线 |
| `serve.py` | 详情页路由，渲染 HTML 前调用 `ensure_prematch_attached` + `attach_market_lanes`；本地默认启动后台 poll 线程，Docker web 需 `--no-poll` |
| `docker-compose.yml` | `web` 使用 `--no-scheduler --no-poll`；`poll` 容器使用 `--interval 300 --interval-pre-jingcai 120` |
| `product_focus.py` | `focus_jingcai_only()`：竞彩过滤与北京时间 11:00 前回退逻辑 |
| `config.py` | `JINGCAI_RELEASE_HOUR = 11` 等竞彩开售时间配置 |
| `download_500.py` | `DownloadResult.league`：透传联赛名到 pipeline |
| `tests/test_odds_parse.py` | 欧亚赔率解析 + `select_major_eu_books` 打码庄名识别 + `build_tick` 写入 `eu_books_major` 测试 |
| `tests/test_poll_interval.py` | 自适应轮询间隔（11 点前 120s / 11 点后 300s）测试 |
| `tests/test_three_lane.py` | 三轨盘口（欧/亚/竞彩）独立与对照规则测试 |
| `tests/test_prematch_desk.py` | 赛前桌、对照摘要、高影响规则、体彩伤停、伤停更新强制重算、天气缺失、日职、ensure 幂等测试 |
| `tests/test_ai_prompt.py` | 盘口桌 prompt 三层结构测试 |
| `tests/test_web_ui.py` | 详情页展示、三轨盘口与对照摘要卡片渲染测试 |
| `tests/test_pivot_jingcai.py` | 竞彩优先级过滤与时间回退测试 |
