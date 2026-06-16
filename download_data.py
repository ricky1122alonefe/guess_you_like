#!/usr/bin/env python3
"""Download free historical data from football-data.co.uk."""

from __future__ import annotations

from pathlib import Path

import requests

BASE = "https://www.football-data.co.uk"
DATA_DIR = Path(__file__).resolve().parent / "data"
LEAGUE_DIR = DATA_DIR / "leagues"
AMERICAS_DIR = DATA_DIR / "americas"

# 最近 10 个赛季（2015/16 - 2024/25）
SEASONS = [
    "1516", "1617", "1718", "1819", "1920",
    "2021", "2122", "2223", "2324", "2425",
]

# 五大联赛（有完整亚盘）
MAIN_LEAGUES = {
    "E0": "英超", "SP1": "西甲", "D1": "德甲", "I1": "意甲", "F1": "法甲",
}

# 次级 + 其他欧洲联赛（有亚盘，样本补充）
EXTRA_LEAGUES = {
    "E1": "英冠", "SP2": "西乙", "D2": "德乙", "I2": "意乙", "F2": "法乙",
    "N1": "荷甲", "P1": "葡超", "B1": "比甲", "T1": "土超", "G1": "希腊超", "SC0": "苏超",
}

# 美洲联赛（单文件多赛季，仅有欧赔收盘，无亚盘；与美国/加拿大世界杯语境相关）
AMERICAS_FILES = {
    "USA.csv": "美国MLS",
    "ARG.csv": "阿根廷",
    "BRA.csv": "巴西",
    "MEX.csv": "墨西哥",
}


def _download(url: str, target: Path) -> None:
    resp = requests.get(url, timeout=90)
    resp.raise_for_status()
    if len(resp.content) < 500:
        raise ValueError("file too small")
    target.write_bytes(resp.content)


def main() -> None:
    LEAGUE_DIR.mkdir(parents=True, exist_ok=True)
    AMERICAS_DIR.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, 0

    for season in SEASONS:
        for code, name in {**MAIN_LEAGUES, **EXTRA_LEAGUES}.items():
            local = f"{code}_{season}.csv"
            target = LEAGUE_DIR / local
            url = f"{BASE}/mmz4281/{season}/{code}.csv"
            print(f"[联赛] {name} {season} ...")
            try:
                _download(url, target)
                print(f"  ok {local} ({target.stat().st_size} bytes)")
                ok += 1
            except Exception as exc:
                print(f"  skip {local}: {exc}")
                fail += 1

    for fname, name in AMERICAS_FILES.items():
        target = AMERICAS_DIR / fname
        url = f"{BASE}/new/{fname}"
        print(f"[美洲] {name} ...")
        try:
            _download(url, target)
            print(f"  ok {fname} ({target.stat().st_size} bytes)")
            ok += 1
        except Exception as exc:
            print(f"  skip {fname}: {exc}")
            fail += 1

    wc = DATA_DIR / "WorldCup2026.xlsx"
    print("[国家队] WorldCup2026.xlsx (2014/18/22 + 2026预选) ...")
    _download(f"{BASE}/WorldCup2026.xlsx", wc)
    print(f"  ok WorldCup2026.xlsx ({wc.stat().st_size} bytes)")
    ok += 1

    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    print("说明:")
    print("  - 联赛 CSV: 有亚盘+欧赔+赛果 (相似亚盘匹配主力)")
    print("  - 美洲 CSV: 仅欧赔+赛果 (无亚盘)")
    print("  - 世界杯 xlsx: 国家队正赛+2026预选赛 (仅欧赔+赛果, 无亚盘)")


if __name__ == "__main__":
    main()
