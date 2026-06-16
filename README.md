# guess_you_like

世界杯 / 竞彩赛事 **赔率分析 + AI 推荐** 本地服务。抓取 500.com 亚盘/欧赔/必发，结合历史相似样本、欧亚互转、盘口套路与多模型 AI，提供 Web 看板、单场详情、当日推荐与世界杯盘路总结。

> **免责声明**：仅供个人学习与研究，不构成任何投注建议。请遵守当地法律法规与数据来源网站的使用条款。

## 功能概览

- **首页看板** `/`：赛程列表、AI 推荐、2串1、SSE 人工干预对话
- **单场详情** `/match/{fixture_id}`：走势图表、相似样本 Top10、深度分析、保存长图
- **当日推荐** `/daily`：稳健/进取档位、保底 2串1
- **世界杯盘路** `/worldcup`：完赛套路归纳、未来 24h 观察、AI 小组战意分析

## 快速开始

### 1. 环境

- Python 3.11+（Docker 镜像使用 3.11）
- PostgreSQL 16（本地或 Docker）
- 可选：Node.js 18+（仅 Cursor SDK 桥接需要）

### 2. 安装

```bash
cd guess_you_like
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Cursor 桥接（可选）
npm install
```

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

详见 `.env.example` 与 `local_secrets.example.py`。

## 项目结构

```
guess_you_like/
├── serve.py              # HTTP 服务入口
├── poll_service.py       # 赔率轮询
├── hourly_pipeline.py    # 整点预测 / AI
├── web_ui.py             # 页面渲染
├── db/                   # PostgreSQL schema & repository
├── data/                 # 历史 CSV、世界杯小组配置等
├── scripts/              # 本地启动、结算、ledger 刷新
└── output/service/       # 运行时输出（git 忽略）
```

## 数据说明

- `data/wc2026_groups.json`：2026 世界杯 48 队小组与赛制策略
- `data/leagues/`、`data/americas/`：历史联赛/美洲样本（football-data 等）
- `data/WorldCup2026.xlsx`：世界杯/预选赛历史赛果（本地分析用）

首次使用若缺少大文件，可运行 `python download_data.py` 补充部分联赛 CSV。

## 开发

```bash
python -m py_compile serve.py web_ui.py
pytest -q
```

## License

MIT — 见 [LICENSE](LICENSE)
