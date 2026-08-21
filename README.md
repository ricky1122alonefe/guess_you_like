# guess_you_like

**竞彩开售联赛**盘口工作台：欧赔 + 亚盘 + 欧亚分歧 + 必发 +（可选）竞彩 SP 对照 + 近 20～50 场总结、主近 20 主场 / 客近 20 客场 + 去水隐含概率 + 勾选 2～3 场串关 EV + 同一结构化数据喂 AI。

> **免责声明**：仅供个人学习与研究，不构成任何投注建议。请遵守当地法律法规与数据来源网站的使用条款。竞彩空 ≠ 无法分析。
> **产品转向**：世界杯专题 → 竞彩开售联赛（2026-08-11）。详见 `docs/PIVOT_JINGCAI_LEAGUES.md`。

## 功能概览

### 主路径（首屏即见）
- **首页看板** `/`：赛程列表（选|比赛|去水倾向|亚盘|必发热|规则倾向|详情），勾选 2～3 场算串关 EV
- **单场详情** `/match/{fixture_id}`：首屏 4 块（①盘口去水 ②战绩 ③规则结论 ④AI），其余折叠
- **复盘** `/review`：命中/Brier/CLV 轻复盘

### 更多（折叠）
- 当日推荐 `/daily`、世界杯盘路 `/worldcup`、亚盘赢盘 `/handicap`、欧亚分歧 `/divergence`、量化回测 `/quant`、Kelly `/kelly`、AI 设置 `/settings/ai`

### 分析引擎
- **去水** `analysis/market/devig.py`：devig_1x2 → p 和=1 + overround（proportional/shin/power）
- **战绩** `analysis/team_form/club_form.py`：近 20～50 场总结 + 主队主场 last20 / 客队客场 last20
- **规则融合** `analysis/result_forecast/`：五源（欧赔+亚盘+必发+历史相似+战绩）→ 1X2 预测
- **串关 EV** `analysis/market/parlay_ev.py`：2～3 场组合 EV（独立假设）
- **AI payload** `analysis/market/ai_payload.py`：结构化包 → markdown，喂外部 AI

## 快速开始

### 1. 环境

- Python **3.9+**（推荐 3.11；Docker 镜像使用 3.11）
- PostgreSQL 16（本地或 Docker）
- 可选：Node.js 18+（仅 Cursor SDK 桥接需要）

### 2. 安装

```bash
cd guess_you_like
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel   # 建议 ≥23，支持 pyproject 可编辑安装
pip install -e ".[dev]"

# 或仅运行时依赖
# pip install -e .

# Cursor 桥接（可选）
npm install
```

安装后可使用统一 CLI：

```bash
guess-you-like --help
guess-you-like serve --host 127.0.0.1 --port 8765
guess-you-like poll --interval 300 --days 7
guess-you-like settle --resettle
```

（别名：`gyl`）

### 3. 配置密钥

```bash
cp local_secrets.example.py local_secrets.py
# 编辑 local_secrets.py，填入 DEEPSEEK_API_KEY 等

cp .env.example .env
# 按需修改 DATABASE_URL
```

`local_secrets.py` 与 `.env` **已在 .gitignore 中，切勿提交**。

### 4. 启动数据库

```bash
docker compose up -d db
# 或 bash scripts/setup_local_pg.sh
```

### 5. 本地开发（推荐）

```bash
bash scripts/run_local.sh          # 仅抓盘 + Web
bash scripts/run_local.sh ai       # + 整点 AI（DeepSeek）
bash scripts/run_local.sh ai-dual  # + DeepSeek + 豆包
```

Web 默认：<http://127.0.0.1:8765>

### 6. Docker 一键

```bash
docker compose up -d
# web → guess-you-like serve · poll → guess-you-like poll
# 镜像内 pip install -e .，与本地 CLI 一致
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `DEEPSEEK_API_KEY` | DeepSeek / 兼容 OpenAI API |
| `ARK_API_KEY` / `DOUBAO_API_KEY` | 火山方舟豆包（可选） |
| `MOONSHOT_API_KEY` | Kimi（需 `AI_ENABLE_KIMI=1`） |
| `CURSOR_API_KEY` | Cursor Composer 桥接（可选） |
| `CURSOR_MODEL` | 默认 `composer-2.5` |
| `FOOTBALL_DATA_API_KEY` | football-data.org 积分榜（可选，motivation 战意维；不配则诚实 missing） |

配好 `FOOTBALL_DATA_API_KEY` 后运行 `guess-you-like standings --refresh` 预拉五大联赛积分榜缓存（TTL 6 小时复用，详见 `docs/DATA_SOURCES.md`）。其余详见 `.env.example` 与 `local_secrets.example.py`。

### AI 模型配置（非密钥）

模型注册表默认见 `data/ai_providers.example.json`。可任选一种方式覆盖：

```bash
# 方式 A：项目级（可提交模板，勿提交含密钥的文件）
cp data/ai_providers.example.json data/ai_providers.json

# 方式 B：运行时目录（推荐，随 output 走）
# POST /api/ai/config 写入 output/service/ai_config.json
```

查询已启用模型：

```bash
curl -s http://127.0.0.1:8765/api/ai/providers?role=chat | python3 -m json.tool
curl -s http://127.0.0.1:8765/api/ai/config | python3 -m json.tool
```

`predict_mode`：`single` 仅主模型 · `multi` 全部启用 · `primary_only` 同 single。环境变量 `AI_PREDICT_MODE` / `AI_PRIMARY_ID` 可临时覆盖。

Web 设置页：<http://127.0.0.1:8765/settings/ai> — 勾选启用、修改 model/roles、测试 API 连通（密钥仍在 `.env`）。

## 项目结构

```
guess_you_like/
├── pyproject.toml        # 包元数据 & 依赖（pip install -e .）
├── cli.py                # 统一 CLI：guess-you-like serve|poll|settle
├── serve.py              # HTTP 服务入口
├── poll_service.py       # 赔率轮询
├── hourly_pipeline.py    # 整点预测 / AI
├── web_ui.py             # 页面渲染
├── db/                   # PostgreSQL schema & repository
├── data/                 # 历史 CSV、世界杯小组配置等
├── docs/                 # 文档（数据来源说明等）
├── scripts/              # 本地启动、结算、ledger 刷新
└── output/service/       # 运行时输出（git 忽略）
```

## 数据说明

- 详见 [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)
- `data/wc2026_groups.json`：2026 世界杯 48 队小组与赛制策略
- `data/leagues/`、`data/americas/`：历史联赛/美洲样本（football-data 等）
- `data/WorldCup2026.xlsx`：世界杯/预选赛历史赛果（本地分析用，可选）

首次使用若缺少大文件，可运行 `python download_data.py` 补充部分联赛 CSV。

## 开发

```bash
pip install -e ".[dev]"
python -m compileall -q .
pytest -q
ruff check .
```

贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。变更记录见 [CHANGELOG.md](CHANGELOG.md)。安全问题见 [SECURITY.md](SECURITY.md)。

## License

MIT — 见 [LICENSE](LICENSE)
