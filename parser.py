"""Parse Titan007 / 球探-style xls exports (亚盘 + 欧赔)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

HANDICAP_MAP = {
    "平手": 0.0,
    "平手/半球": -0.25,
    "半球": -0.5,
    "半球/一球": -0.75,
    "一球": -1.0,
    "一球/球半": -1.25,
    "球半": -1.5,
    "球半/两球": -1.75,
    "两球": -2.0,
    "受平手/半球": 0.25,
    "受让平手/半球": 0.25,
    "受半球": 0.5,
    "受半球/一球": 0.75,
    "受一球": 1.0,
    "受球半": 0.5,
    "受球半/两球": 1.75,
    "球半/两球": -1.75,
}


def parse_handicap(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace("升", "").replace("降", "").strip()
    text = text.split("/")[0].strip()
    for key, line in sorted(HANDICAP_MAP.items(), key=lambda x: -len(x[0])):
        if key in text:
            return line
    try:
        return float(text)
    except ValueError:
        return None


def _match_name_from_path(path: Path) -> str:
    name = path.stem
    name = re.sub(r"\(亚盘\)$", "", name)
    name = re.sub(r"\(世界杯\)欧洲数据$", "", name)
    name = re.sub(r"\(欧赔\)$", "", name)
    return name


def _is_ah_file(path: Path) -> bool:
    return "亚盘" in path.stem


def _is_eu_file(path: Path) -> bool:
    stem = path.stem
    return "欧洲" in stem or "欧赔" in stem


def pair_match_files(paths: list[str | Path]) -> list[tuple[str, str]]:
    """Auto-pair (亚盘).xls with (欧赔).xls by match name. Supports 2, 4, 6... files."""
    if len(paths) < 2 or len(paths) % 2 != 0:
        raise ValueError(f"需要偶数个 xls 文件（每场 2 个：亚盘+欧赔），当前 {len(paths)} 个")

    ah_files: dict[str, Path] = {}
    eu_files: dict[str, Path] = {}
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        name = _match_name_from_path(path)
        if _is_ah_file(path):
            if name in ah_files:
                raise ValueError(f"重复的亚盘文件: {name}")
            ah_files[name] = path
        elif _is_eu_file(path):
            if name in eu_files:
                raise ValueError(f"重复的欧赔文件: {name}")
            eu_files[name] = path
        else:
            raise ValueError(f"无法识别文件类型（需含「亚盘」或「欧洲/欧赔」）: {path}")

    all_names = sorted(set(ah_files) | set(eu_files))
    missing_ah = [n for n in all_names if n not in ah_files]
    missing_eu = [n for n in all_names if n not in eu_files]
    if missing_ah or missing_eu:
        parts = []
        if missing_ah:
            parts.append(f"缺亚盘: {', '.join(missing_ah)}")
        if missing_eu:
            parts.append(f"缺欧赔: {', '.join(missing_eu)}")
        raise ValueError("；".join(parts))

    return [(str(ah_files[n]), str(eu_files[n])) for n in all_names]


def _find_row(df: pd.DataFrame, pattern: str) -> pd.Series | None:
    mask = df[0].astype(str).str.contains(pattern, case=False, na=False)
    rows = df[mask]
    if rows.empty:
        return None
    return rows.iloc[0]


def hk_to_decimal(water: float | None) -> float | None:
    """球探港盘水位 -> football-data 用的欧赔小数格式 (约等于 water + 1)。"""
    if water is None:
        return None
    if water <= 1.5:
        return round(water + 1.0, 3)
    return water


@dataclass
class MatchOdds:
    match_name: str
    ah_line: float | None
    ah_home_water: float | None
    ah_away_water: float | None
    ah_open_line: float | None
    ah_open_home_water: float | None
    ah_open_away_water: float | None
    eu_home: float | None
    eu_draw: float | None
    eu_away: float | None
    eu_open_home: float | None
    eu_open_draw: float | None
    eu_open_away: float | None
    bookmaker: str = "pinnacle"

    @property
    def ah_home_decimal(self) -> float | None:
        return hk_to_decimal(self.ah_home_water)

    @property
    def ah_away_decimal(self) -> float | None:
        return hk_to_decimal(self.ah_away_water)


def odds_snapshot(current: MatchOdds, phase: str = "close") -> MatchOdds:
    """Build MatchOdds for open or closing (live) phase."""
    if phase == "open":
        return MatchOdds(
            match_name=current.match_name,
            ah_line=current.ah_open_line,
            ah_home_water=current.ah_open_home_water,
            ah_away_water=current.ah_open_away_water,
            ah_open_line=current.ah_open_line,
            ah_open_home_water=current.ah_open_home_water,
            ah_open_away_water=current.ah_open_away_water,
            eu_home=current.eu_open_home,
            eu_draw=current.eu_open_draw,
            eu_away=current.eu_open_away,
            eu_open_home=current.eu_open_home,
            eu_open_draw=current.eu_open_draw,
            eu_open_away=current.eu_open_away,
            bookmaker=current.bookmaker,
        )
    return current


def _cell_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.lower() == "false" or s == "nan":
        return ""
    return s


def _is_500_ah(df: pd.DataFrame) -> bool:
    if len(df) < 5:
        return False
    if _find_row(df, r"Pi|平博|Pinnacle|平均值") is not None:
        return False
    c1 = _cell_str(df.iloc[0, 1]) if df.shape[1] > 1 else ""
    return bool(re.search(r"盘|口|water", c1, re.I)) or df.iloc[2, 1:4].notna().sum() >= 2


def _pick_handicap_from_rows(df: pd.DataFrame, col: int, *, start: int = 5) -> float | None:
    for i in range(len(df) - 1, start - 1, -1):
        raw = df.iloc[i, col]
        if isinstance(raw, (int, float)) and not (isinstance(raw, float) and pd.isna(raw)):
            continue
        text = _cell_str(raw)
        if not text:
            continue
        line = parse_handicap(text)
        if line is not None:
            return line
    return None


def _parse_ah_500(path: Path, df: pd.DataFrame) -> dict:
    avg = df.iloc[2]
    ah_line = _pick_handicap_from_rows(df, 2) or _pick_handicap_from_rows(df, 6)
    ah_open_line = _pick_handicap_from_rows(df, 6) or ah_line

    pin = _find_row(df, r"Pi|平博")
    src = pin if pin is not None else avg
    if pin is not None:
        line_live = parse_handicap(_cell_str(pin[2]))
        line_open = parse_handicap(_cell_str(pin[6]))
        return {
            "match_name": _match_name_from_path(path),
            "bookmaker": "pinnacle",
            "ah_line": line_live or ah_line,
            "ah_home_water": _to_float(pin[1]),
            "ah_away_water": _to_float(pin[3]),
            "ah_open_line": line_open or ah_open_line or line_live,
            "ah_open_home_water": _to_float(pin[5]),
            "ah_open_away_water": _to_float(pin[7]),
        }

    return {
        "match_name": _match_name_from_path(path),
        "bookmaker": "average",
        "ah_line": ah_line,
        "ah_home_water": _to_float(avg[1]),
        "ah_away_water": _to_float(avg[3]),
        "ah_open_line": ah_open_line,
        "ah_open_home_water": _to_float(avg[5]),
        "ah_open_away_water": _to_float(avg[7]),
    }


def _is_500_eu(df: pd.DataFrame) -> bool:
    head = _cell_str(df.iloc[0, 0])
    return head == "欧赔公司" or "欧赔公司" in head


def _parse_eu_500(path: Path, df: pd.DataFrame) -> dict:
    pin = _find_row(df, r"Pinnacle|平博")
    if pin is None or not _to_float(pin[1]):
        pin = _find_row(df, "平均值")
    if pin is None or not _to_float(pin[1]):
        raise ValueError(f"cannot find pinnacle/average row in {path}")

    idx = int(pin.name)
    open_row = df.iloc[idx + 1] if idx + 1 < len(df) else None
    has_open = (
        open_row is not None
        and not _cell_str(open_row[0])
        and _to_float(open_row[1]) is not None
    )

    return {
        "match_name": _match_name_from_path(path),
        "eu_home": _to_float(pin[1]),
        "eu_draw": _to_float(pin[2]),
        "eu_away": _to_float(pin[3]),
        "eu_open_home": _to_float(open_row[1]) if has_open else None,
        "eu_open_draw": _to_float(open_row[2]) if has_open else None,
        "eu_open_away": _to_float(open_row[3]) if has_open else None,
    }


def parse_ah_xls(path: str | Path) -> dict:
    path = Path(path)
    df = pd.read_excel(path, header=None)
    if _is_500_ah(df):
        return _parse_ah_500(path, df)
    pin = _find_row(df, r"Pi|平博|Pinnacle")
    avg = _find_row(df, "平均值")
    row = pin if pin is not None else avg
    if row is None:
        raise ValueError(f"cannot find pinnacle/average row in {path}")

    return {
        "match_name": _match_name_from_path(path),
        "bookmaker": "pinnacle" if pin is not None else "average",
        "ah_line": parse_handicap(row[2]),
        "ah_home_water": _to_float(row[1]),
        "ah_away_water": _to_float(row[3]),
        "ah_open_line": parse_handicap(row[6]),
        "ah_open_home_water": _to_float(row[5]),
        "ah_open_away_water": _to_float(row[7]),
    }


def parse_eu_xls(path: str | Path) -> dict:
    path = Path(path)
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    for name in xl.sheet_names:
        if "上下" in name:
            sheet = name
            break
        if "左右" in name and "上下" not in sheet:
            sheet = name
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    if _is_500_eu(df):
        return _parse_eu_500(path, df)
    avg = _find_row(df, "平均值")
    if avg is None:
        raise ValueError(f"cannot find average row in {path}")

    return {
        "match_name": _match_name_from_path(path),
        "eu_home": _to_float(avg[1]),
        "eu_draw": _to_float(avg[2]),
        "eu_away": _to_float(avg[3]),
        "eu_open_home": _to_float(avg[11]) if len(avg) > 13 else None,
        "eu_open_draw": _to_float(avg[12]) if len(avg) > 13 else None,
        "eu_open_away": _to_float(avg[13]) if len(avg) > 13 else None,
    }


def _to_float(value) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_match_pair(ah_path: str | Path, eu_path: str | Path) -> MatchOdds:
    ah = parse_ah_xls(ah_path)
    eu = parse_eu_xls(eu_path)

    if ah["ah_line"] is None and eu.get("eu_home") and eu.get("eu_away"):
        try:
            from market_patterns import eu_to_ah_line
            ah["ah_line"] = eu_to_ah_line(eu["eu_home"], eu["eu_draw"], eu["eu_away"])
        except Exception:
            pass
    if ah["ah_open_line"] is None and eu.get("eu_open_home") and eu.get("eu_open_away"):
        try:
            from market_patterns import eu_to_ah_line
            ah["ah_open_line"] = eu_to_ah_line(
                eu["eu_open_home"], eu["eu_open_draw"], eu["eu_open_away"],
            )
        except Exception:
            pass
    if ah["ah_open_line"] is None:
        ah["ah_open_line"] = ah["ah_line"]

    return MatchOdds(
        match_name=ah["match_name"],
        ah_line=ah["ah_line"],
        ah_home_water=ah["ah_home_water"],
        ah_away_water=ah["ah_away_water"],
        ah_open_line=ah["ah_open_line"],
        ah_open_home_water=ah["ah_open_home_water"],
        ah_open_away_water=ah["ah_open_away_water"],
        eu_home=eu["eu_home"],
        eu_draw=eu["eu_draw"],
        eu_away=eu["eu_away"],
        eu_open_home=eu["eu_open_home"],
        eu_open_draw=eu["eu_open_draw"],
        eu_open_away=eu["eu_open_away"],
        bookmaker=ah["bookmaker"],
    )
