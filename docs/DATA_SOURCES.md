# Data sources & licensing

This project combines **public sports statistics** with **live data scraped from third-party websites**. Understand the limits before redistributing or commercial use.

## Bundled static data (`data/`)

| Path | Origin | Notes |
|------|--------|--------|
| `data/leagues/*.csv` | [football-data.co.uk](https://www.football-data.co.uk/) | Historical league results; check their site for terms |
| `data/americas/*.csv` | Same / project-maintained exports | National team samples |
| `data/openfootball/*.txt` | [Open Football](https://github.com/openfootball) | Text fixtures; MIT-style open data |
| `data/wc2026_groups.json` | Project-maintained | 2026 WC group draw & strategy notes |
| `data/wc2026_knockout_bracket.json` | Project-maintained | Knockout bracket template |
| `data/elo_ratings.json` | Generated at runtime | Derived from settled results |

Large optional files (e.g. `WorldCup2026.xlsx`) may not be in the repo; run `python download_data.py` where documented.

## Live / runtime data

| Source | Usage |
|--------|--------|
| odds.500.com / live.500.com / liansai.500.com | Odds, fixtures, scores (scraping) |
| sporttery.cn (via poll) | Jingcai SP context where available |

**You must comply with each website's terms of service and robots policy.** This software is for personal research; the authors do not grant rights to the scraped content.

## AI providers

Optional keys (DeepSeek, Volcengine Ark, Moonshot, Cursor) are subject to each provider's API terms. Keys stay in `.env` / `local_secrets.py` — never commit them.

## Disclaimer

Outputs are **not** betting advice. Tournament names and team lists are used descriptively; trademarks belong to their owners.
