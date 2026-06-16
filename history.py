"""Load free historical data from football-data.co.uk."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ah import ah_settle, result_1x2

DATA_DIR = Path(__file__).resolve().parent / "data"
LEAGUE_DIR = DATA_DIR / "leagues"
AMERICAS_DIR = DATA_DIR / "americas"
WORLD_CUP_XLSX = DATA_DIR / "WorldCup2026.xlsx"


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    cleaned = [
        df.dropna(axis=1, how="all")
        for df in frames
        if df is not None and not df.empty
    ]
    if not cleaned:
        return pd.DataFrame()
    return pd.concat(cleaned, ignore_index=True)


def load_league_history() -> pd.DataFrame:
    frames = []
    for csv_path in sorted(LEAGUE_DIR.glob("*.csv")):
        df = pd.read_csv(csv_path, encoding="latin-1")
        df["source"] = csv_path.stem
        frames.append(_normalize_league(df))
    for csv_path in sorted(AMERICAS_DIR.glob("*.csv")):
        df = pd.read_csv(csv_path, encoding="latin-1")
        df["source"] = csv_path.stem
        frames.append(_normalize_americas(df))
    if not frames:
        raise FileNotFoundError(f"no csv in {LEAGUE_DIR} or {AMERICAS_DIR}, run download_data.py")
    return _concat_frames(frames)


def load_worldcup_history() -> pd.DataFrame:
    if not WORLD_CUP_XLSX.exists():
        return pd.DataFrame()

    frames = []
    with pd.ExcelFile(WORLD_CUP_XLSX) as xl:
        for sheet in xl.sheet_names:
            if not sheet.lower().startswith("worldcup"):
                continue
            raw = pd.read_excel(xl, sheet_name=sheet)
            raw = raw.rename(
                columns={
                    "Home": "HomeTeam",
                    "Away": "AwayTeam",
                    "Date": "Date",
                    "HGFT": "FTHG",
                    "AGFT": "FTAG",
                    "HG": "FTHG",
                    "AG": "FTAG",
                }
            )
            for col, *fallbacks in [
                ("PH", "Pinny-H", "bet365-H", "H-Avg"),
                ("PD", "Pinny-D", "bet365-D", "D-Avg"),
                ("PA", "Pinny-A", "bet365-A", "A-Avg"),
            ]:
                series = None
                for name in (col, *fallbacks):
                    if name in raw.columns:
                        series = raw[name] if series is None else series.fillna(raw[name])
                raw[col] = series
            raw["source"] = sheet
            comp = "qualifier" if "qualifier" in sheet.lower() else "worldcup"
            frames.append(_normalize_worldcup(raw, comp))
    if not frames:
        return pd.DataFrame()
    return _concat_frames(frames)


def _normalize_league(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["date"] = df.get("Date")
    out["home"] = df.get("HomeTeam")
    out["away"] = df.get("AwayTeam")
    out["score_h"] = pd.to_numeric(df.get("FTHG"), errors="coerce")
    out["score_a"] = pd.to_numeric(df.get("FTAG"), errors="coerce")
    out["source"] = df.get("source")
    # 初盘（opening）— 精算师定价，优先用于规律统计
    out["eu_home_open"] = pd.to_numeric(df.get("B365H"), errors="coerce")
    out["eu_draw_open"] = pd.to_numeric(df.get("B365D"), errors="coerce")
    out["eu_away_open"] = pd.to_numeric(df.get("B365A"), errors="coerce")
    out["ah_line_open"] = pd.to_numeric(df.get("AHh"), errors="coerce")
    out["ah_home_water_open"] = pd.to_numeric(df.get("AvgAHH"), errors="coerce")
    out["ah_away_water_open"] = pd.to_numeric(df.get("AvgAHA"), errors="coerce")
    # 临盘/收盘（closing）
    out["eu_home"] = pd.to_numeric(df.get("B365CH", df.get("B365H")), errors="coerce")
    out["eu_draw"] = pd.to_numeric(df.get("B365CD", df.get("B365D")), errors="coerce")
    out["eu_away"] = pd.to_numeric(df.get("B365CA", df.get("B365A")), errors="coerce")
    out["ah_line"] = pd.to_numeric(df.get("AHCh", df.get("AHh")), errors="coerce")
    out["ah_home_water"] = pd.to_numeric(df.get("AvgCAHH", df.get("AvgAHH")), errors="coerce")
    out["ah_away_water"] = pd.to_numeric(df.get("AvgCAHA", df.get("AvgAHA")), errors="coerce")
    out["competition"] = "league"
    return _finalize(out)


def _normalize_americas(df: pd.DataFrame) -> pd.DataFrame:
    """new/USA.csv 等：多赛季合并，只有欧赔收盘。"""
    out = pd.DataFrame()
    out["date"] = df.get("Date")
    out["home"] = df.get("Home")
    out["away"] = df.get("Away")
    out["score_h"] = pd.to_numeric(df.get("HG"), errors="coerce")
    out["score_a"] = pd.to_numeric(df.get("AG"), errors="coerce")
    out["source"] = df.get("source")
    out["eu_home"] = pd.to_numeric(
        df.get("B365CH", df.get("AvgCH", df.get("PSCH"))), errors="coerce"
    )
    out["eu_draw"] = pd.to_numeric(
        df.get("B365CD", df.get("AvgCD", df.get("PSCD"))), errors="coerce"
    )
    out["eu_away"] = pd.to_numeric(
        df.get("B365CA", df.get("AvgCA", df.get("PSCA"))), errors="coerce"
    )
    out["ah_line"] = pd.NA
    out["ah_home_water"] = pd.NA
    out["ah_away_water"] = pd.NA
    out["competition"] = "americas"
    return _finalize(out)


def _normalize_worldcup(df: pd.DataFrame, competition: str) -> pd.DataFrame:
    out = pd.DataFrame()
    out["date"] = df.get("Date")
    out["home"] = df.get("HomeTeam")
    out["away"] = df.get("AwayTeam")
    out["score_h"] = pd.to_numeric(df.get("FTHG"), errors="coerce")
    out["score_a"] = pd.to_numeric(df.get("FTAG"), errors="coerce")
    out["source"] = df.get("source")
    out["eu_home"] = pd.to_numeric(df.get("PH", df.get("B365H")), errors="coerce")
    out["eu_draw"] = pd.to_numeric(df.get("PD", df.get("B365D")), errors="coerce")
    out["eu_away"] = pd.to_numeric(df.get("PA", df.get("B365A")), errors="coerce")
    out["ah_line"] = pd.NA
    out["ah_home_water"] = pd.NA
    out["ah_away_water"] = pd.NA
    out["competition"] = competition
    return _finalize(out)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["score_h", "score_a"]).copy()
    df["score_h"] = df["score_h"].astype(int)
    df["score_a"] = df["score_a"].astype(int)
    df["result_1x2"] = df.apply(lambda r: result_1x2(r["score_h"], r["score_a"]), axis=1)

    def settle(row, side):
        if pd.isna(row["ah_line"]):
            return pd.NA
        return ah_settle(int(row["score_h"]), int(row["score_a"]), float(row["ah_line"]), side)

    df["ah_home_result"] = df.apply(lambda r: settle(r, "home"), axis=1)
    df["ah_away_result"] = df.apply(lambda r: settle(r, "away"), axis=1)
    df["move_tag"] = df.apply(_hist_move_tag, axis=1)
    return df.reset_index(drop=True)


def _hist_move_tag(row) -> str:
    tags: list[str] = []
    if pd.notna(row.get("ah_line_open")) and pd.notna(row.get("ah_line")):
        d = float(row["ah_line"]) - float(row["ah_line_open"])
        if d < -0.01:
            tags.append("升盘")
        elif d > 0.01:
            tags.append("降盘")
        else:
            tags.append("盘口稳定")
    hw_o, hw_c = row.get("ah_home_water_open"), row.get("ah_home_water")
    if pd.notna(hw_o) and pd.notna(hw_c) and abs(float(hw_c) - float(hw_o)) >= 0.03:
        tags.append("上水变动")
    aw_o, aw_c = row.get("ah_away_water_open"), row.get("ah_away_water")
    if pd.notna(aw_o) and pd.notna(aw_c) and abs(float(aw_c) - float(aw_o)) >= 0.03:
        tags.append("下水变动")
    return " / ".join(tags) if tags else "仅收盘数据"


def load_all_history() -> pd.DataFrame:
    league = load_league_history()
    wc = load_worldcup_history()
    if wc.empty:
        return league
    return _concat_frames([league, wc])
