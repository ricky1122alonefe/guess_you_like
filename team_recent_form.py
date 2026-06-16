"""Recent national-team form (qualifiers / int'l) from football-data for AI context."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

import config as app_cfg
from share_card import split_teams
from wc_standings_fetch import normalize_team

log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent / "data" / "WorldCup2026.xlsx"
GROUPS_PATH = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"


def _parse_dates(values) -> pd.Series:
    series = pd.Series(values)
    text = series.astype("string").str.strip()
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%m/%d/%y"):
        missing = out.isna() & text.notna() & (text != "") & (text != "—")
        if not missing.any():
            break
        parsed = pd.to_datetime(text[missing], format=fmt, errors="coerce")
        out.loc[missing] = parsed
    return out


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    cleaned = [
        df.dropna(axis=1, how="all")
        for df in frames
        if df is not None and not df.empty
    ]
    if not cleaned:
        return pd.DataFrame()
    return pd.concat(cleaned, ignore_index=True)


def _load_alias_maps() -> tuple[dict[str, str], dict[str, list[str]]]:
    """name (any variant) -> canonical CN; canonical CN -> [aliases]."""
    to_cn: dict[str, str] = {}
    by_cn: dict[str, list[str]] = {}
    if not GROUPS_PATH.is_file():
        return to_cn, by_cn
    try:
        data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return to_cn, by_cn
    for teams in (data.get("groups") or {}).values():
        for cn in teams:
            to_cn[cn] = cn
            by_cn.setdefault(cn, [])
    for cn, aliases in (data.get("aliases") or {}).items():
        to_cn[cn] = cn
        al = list(aliases or [])
        by_cn[cn] = al
        for a in al:
            to_cn[a] = cn
    extra = {
        "Bosnia & Herzegovina": "波黑",
        "Bosnia-Herzegovina": "波黑",
        "Czech Republic": "捷克",
        "Czechia": "捷克",
        "Turkey": "土耳其",
        "Turkiye": "土耳其",
        "Korea Republic": "韩国",
        "South Korea": "韩国",
        "United States": "美国",
        "USA": "美国",
        "Ivory Coast": "科特迪瓦",
        "Cote d'Ivoire": "科特迪瓦",
        "IR Iran": "伊朗",
        "Cape Verde": "佛得角",
        "Saudi Arabia": "沙特",
        "DR Congo": "刚果(金)",
        "Congo DR": "刚果(金)",
        "Curacao": "库拉索",
        "Curaçao": "库拉索",
    }
    for en, cn in extra.items():
        if cn not in to_cn.get(cn, cn):
            by_cn.setdefault(cn, []).append(en)
        to_cn[en] = cn
    return to_cn, by_cn


_TO_CN, _ALIASES_BY_CN = _load_alias_maps()


def canonical_team(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return s
    if s in _TO_CN:
        return _TO_CN[s]
    norm = normalize_team(s)
    if norm in _TO_CN:
        return _TO_CN[norm]
    return norm


def _match_variants(cn: str) -> set[str]:
    variants = {cn}
    for a in _ALIASES_BY_CN.get(cn, []):
        variants.add(a)
    return variants


@lru_cache(maxsize=1)
def _load_openfootball_as_df() -> pd.DataFrame:
    try:
        from openfootball_intl import load_openfootball_matches
        rows = load_openfootball_matches()
    except Exception as exc:
        log.debug("openfootball 跳过: %s", exc)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = _parse_dates(df["date"])
    df = df.dropna(subset=["date"])
    for col in ("eu_home", "eu_draw", "eu_away"):
        df[col] = pd.NA
    return df.sort_values("date", ascending=False).reset_index(drop=True)


@lru_cache(maxsize=1)
def _load_international_matches() -> pd.DataFrame:
    if not DATA_PATH.is_file():
        return _load_openfootball_as_df()
    try:
        raw = pd.read_excel(DATA_PATH, sheet_name="WorldCup2026Qualifiers")
    except Exception as exc:
        log.warning("无法读取国际赛数据: %s", exc)
        return _load_openfootball_as_df()
    df = pd.DataFrame()
    df["date"] = _parse_dates(raw.get("Date"))
    df["home_raw"] = raw.get("Home").astype(str)
    df["away_raw"] = raw.get("Away").astype(str)
    df["home_cn"] = df["home_raw"].map(canonical_team)
    df["away_cn"] = df["away_raw"].map(canonical_team)
    df["score_h"] = pd.to_numeric(raw.get("HG"), errors="coerce")
    df["score_a"] = pd.to_numeric(raw.get("AG"), errors="coerce")
    for col, src in (
        ("eu_home", "H_Avg"),
        ("eu_draw", "D_Avg"),
        ("eu_away", "A_Avg"),
    ):
        df[col] = pd.to_numeric(raw.get(src), errors="coerce")
    df = df.dropna(subset=["date", "score_h", "score_a"]).copy()
    df["score_h"] = df["score_h"].astype(int)
    df["score_a"] = df["score_a"].astype(int)
    df["competition"] = "国际赛/预选赛"
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    extra = _load_openfootball_as_df()
    if extra.empty:
        return df
    combined = _concat_frames([df, extra])
    combined = combined.drop_duplicates(
        subset=["date", "home_raw", "away_raw", "score_h", "score_a"],
        keep="first",
    )
    return combined.sort_values("date", ascending=False).reset_index(drop=True)


def _team_mask(df: pd.DataFrame, team_cn: str) -> pd.Series:
    variants = _match_variants(team_cn)
    return (
        df["home_cn"].eq(team_cn)
        | df["away_cn"].eq(team_cn)
        | df["home_raw"].isin(variants)
        | df["away_raw"].isin(variants)
    )


def _perspective_row(row: pd.Series, team_cn: str) -> dict[str, Any]:
    is_home = row["home_cn"] == team_cn or row["home_raw"] in _match_variants(team_cn)
    sh, sa = int(row["score_h"]), int(row["score_a"])
    if is_home:
        gf, ga, opp = sh, sa, row["away_raw"]
        venue = "主"
        eu = (row.get("eu_home"), row.get("eu_draw"), row.get("eu_away"))
    else:
        gf, ga, opp = sa, sh, row["home_raw"]
        venue = "客"
        eu = (row.get("eu_away"), row.get("eu_draw"), row.get("eu_home"))
    if gf > ga:
        res_cn = "胜"
    elif gf == ga:
        res_cn = "平"
    else:
        res_cn = "负"
    odds_txt = "—"
    if all(pd.notna(x) for x in eu):
        odds_txt = f"{eu[0]:.2g}/{eu[1]:.2g}/{eu[2]:.2g}"
    return {
        "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else "—",
        "opponent": str(opp),
        "venue": venue,
        "score": f"{gf}-{ga}",
        "result": res_cn,
        "goals_for": gf,
        "goals_against": ga,
        "eu_odds": odds_txt,
        "competition": row.get("competition") or "国际赛",
    }


def _summarize_team(matches: list[dict[str, Any]], team_cn: str, *, window_days: int) -> dict[str, Any]:
    if not matches:
        return {
            "team": team_cn,
            "window_days": window_days,
            "match_count": 0,
            "summary": f"{team_cn}：近 {window_days} 天无已入库国际赛记录",
            "recent_matches": [],
        }
    wins = sum(1 for m in matches if m["result"] == "胜")
    draws = sum(1 for m in matches if m["result"] == "平")
    losses = sum(1 for m in matches if m["result"] == "负")
    gf = sum(m["goals_for"] for m in matches)
    ga = sum(m["goals_against"] for m in matches)
    n = len(matches)
    avg_gf = round(gf / n, 2)
    avg_total = round((gf + ga) / n, 2)
    home_n = sum(1 for m in matches if m["venue"] == "主")
    away_n = n - home_n
    summary = (
        f"{team_cn} 近{n}场（{window_days}天内）：{wins}胜{draws}平{losses}负，"
        f"进{gf}失{ga}，场均进{avg_gf}球/总{avg_total}球（主{home_n}客{away_n}）"
    )
    return {
        "team": team_cn,
        "window_days": window_days,
        "match_count": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": gf,
        "goals_against": ga,
        "avg_goals_for": avg_gf,
        "avg_total_goals": avg_total,
        "summary": summary,
        "recent_matches": matches,
    }


def build_team_recent_form(
    home_cn: str,
    away_cn: str,
    *,
    days: int | None = None,
    max_matches: int | None = None,
    reference_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Build recent int'l form for both teams (qualifiers / int'l in WorldCup2026 xlsx).
    Returns empty blocks when data file or team names unavailable.
    """
    days = days if days is not None else getattr(app_cfg, "TEAM_FORM_DAYS", 365)
    max_matches = max_matches if max_matches is not None else getattr(
        app_cfg, "TEAM_FORM_MAX_MATCHES", 8,
    )
    home = canonical_team(home_cn)
    away = canonical_team(away_cn)
    df = _load_international_matches()
    if df.empty or not home or not away:
        return {
            "home": _summarize_team([], home or home_cn, window_days=days),
            "away": _summarize_team([], away or away_cn, window_days=days),
            "head_to_head": [],
            "data_source": "football-data WorldCup2026Qualifiers",
            "available": False,
            "note": "国际赛近期数据未加载或队名无法识别",
        }

    ref = reference_date or datetime.now()
    if hasattr(ref, "tzinfo") and ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    cutoff = ref - timedelta(days=days)
    recent = df[df["date"] >= cutoff]

    def _team_matches(team: str) -> list[dict[str, Any]]:
        sub = recent[_team_mask(recent, team)].head(max_matches * 3)
        out: list[dict[str, Any]] = []
        for _, row in sub.iterrows():
            out.append(_perspective_row(row, team))
            if len(out) >= max_matches:
                break
        return out

    h2h_rows = recent[
        (_team_mask(recent, home) & _team_mask(recent, away))
    ].head(3)
    h2h = []
    for _, row in h2h_rows.iterrows():
        h2h.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "match": f"{row['home_raw']} {int(row['score_h'])}-{int(row['score_a'])} {row['away_raw']}",
            "eu_odds": (
                f"{row['eu_home']:.2g}/{row['eu_draw']:.2g}/{row['eu_away']:.2g}"
                if pd.notna(row["eu_home"]) else "—"
            ),
        })

    home_block = _summarize_team(_team_matches(home), home, window_days=days)
    away_block = _summarize_team(_team_matches(away), away, window_days=days)
    note = (
        f"数据来源 football-data 国际赛/预选赛 + openfootball 2026 赛果（近{days}天）；"
        "不含未入库友谊赛；队名经 wc2026_groups 别名映射"
    )
    return {
        "home": home_block,
        "away": away_block,
        "head_to_head": h2h,
        "data_source": "football-data WorldCup2026Qualifiers",
        "available": bool(home_block["match_count"] or away_block["match_count"]),
        "note": note,
    }


def build_team_recent_form_from_match(match_name: str, **kwargs) -> dict[str, Any]:
    home, away = split_teams(match_name or "")
    if not home or not away:
        return build_team_recent_form("", "", **kwargs)
    return build_team_recent_form(home, away, **kwargs)


def form_headline(form: dict[str, Any]) -> str:
    """One-line digest for evidence brief / UI."""
    if not form.get("available"):
        return form.get("note") or "双方近期国际赛数据不足"
    h = (form.get("home") or {}).get("summary") or ""
    a = (form.get("away") or {}).get("summary") or ""
    parts = [p for p in (h, a) if p]
    h2h = form.get("head_to_head") or []
    if h2h:
        parts.append(f"近一年交锋 {len(h2h)} 场：{h2h[0].get('match')}")
    return "；".join(parts)
