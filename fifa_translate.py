"""Translate FIFA preview English text to Chinese for Douyin/share cards."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent / "data" / "fifa_translate_cache.json"

_LATIN_RUN = re.compile(r"[A-Za-z]{3,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")

_STAGE_ZH = {
    "Round of 32": "16强",
    "Round of 16": "8强",
    "Quarter-finals": "四分之一决赛",
    "Semi-finals": "半决赛",
    "Third place": "三四名决赛",
    "Final": "决赛",
    "Group stage": "小组赛",
}

_STADIUM_ZH = {
    "Houston Stadium": "休斯顿体育场",
    "NRG Stadium": "休斯顿体育场",
    "MetLife Stadium": "大都会人寿球场",
    "New York New Jersey Stadium": "纽约新泽西体育场",
    "SoFi Stadium": "SoFi 球场",
    "AT&T Stadium": "AT&T 球场",
    "Mercedes-Benz Stadium": "梅赛德斯-奔驰球场",
    "Hard Rock Stadium": "Hard Rock 球场",
    "Lumen Field": "流明球场",
    "BMO Field": "BMO 球场",
    "BC Place": "BC Place 球场",
    "Estadio Azteca": "阿兹特克球场",
    "Azteca Stadium": "阿兹特克球场",
}

# Protect tokens during machine translation (team / player names).
_PROTECT_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = []


def _load_protections() -> list[tuple[re.Pattern[str], str]]:
    global _PROTECT_REPLACEMENTS
    if _PROTECT_REPLACEMENTS:
        return _PROTECT_REPLACEMENTS
    try:
        groups_path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
        data = json.loads(groups_path.read_text(encoding="utf-8"))
        tokens: set[str] = set()
        for cn, aliases in (data.get("aliases") or {}).items():
            tokens.add(cn)
            for alias in aliases or []:
                if isinstance(alias, str) and alias.isascii() and len(alias) > 2:
                    tokens.add(alias)
        for token in sorted(tokens, key=len, reverse=True):
            pat = re.compile(rf"\b{re.escape(token)}\b", re.I)
            _PROTECT_REPLACEMENTS.append((pat, f"⟦{token}⟧"))
    except Exception as exc:
        log.debug("FIFA translate protections skipped: %s", exc)
    return _PROTECT_REPLACEMENTS


_FOOTBALL_PHRASE_ZH = {
    "FIFA World Cup 2026™": "2026世界杯",
    "FIFA World Cup 2026": "2026世界杯",
    "World Cup 2026": "2026世界杯",
    "World Cup": "世界杯",
    "group stage": "小组赛",
    "knockout stage": "淘汰赛",
    "Round of 32": "16强",
    "top spot": "小组第一",
    "second in Group": "小组第二",
    "The Seleção": "巴西队",
    "Seleção": "巴西队",
    "firing on all cylinders": "状态火热，全线进攻",
    "group stage campaign": "小组赛",
    "solid group stage": "小组赛表现稳健",
    "very solid group stage": "小组赛表现非常稳健",
    "arrive into the knockout stage": "进入淘汰赛阶段",
    "knockout stage firing on all cylinders": "淘汰赛状态火热、全线开火",
}

# 整句模板 — FIFA 预览高频句，避免 MyMemory 乱译
_FIFA_CURATED_SENTENCES: list[tuple[str, str]] = [
    (
        r"The Seleção\s*arrive into the knockout stage firing on all cylinders\.?",
        "巴西队进入淘汰赛，状态火热、全线进攻。",
    ),
    (
        r"Japan enjoyed a very solid group stage campaign as well\.?",
        "日本小组赛同样表现稳健。",
    ),
    (
        r"they collected successive 3-0 victories over Haiti and Scotland with Vinicius Jr\. notching four goals\.?",
        "随后连赢海地、苏格兰，维尼修斯小组赛攻入四球。",
    ),
    (
        r"Daichi Kamada and Ayase Ueda have each scored a pair of goals\.?",
        "镰田大地与上田绮世各有两球入账。",
    ),
]

_BROKEN_ZH_FIXES: list[tuple[str, str]] = [
    (r"坚小组赛表现固", "小组赛表现同样稳健"),
    (r"进入所有气缸", "状态火热，全线进攻"),
    (r"也非常坚", "同样表现稳健"),
    (r"气缸", "状态"),
]


def needs_zh_translate(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    return bool(_LATIN_RUN.search(s))


def _cache_load() -> dict[str, str]:
    if not CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _cache_save(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _pre_substitute_teams(
    text: str,
    *,
    home_cn: str = "",
    away_cn: str = "",
    home_en: str = "",
    away_en: str = "",
) -> str:
    out = str(text or "")
    for en, cn in ((home_en, home_cn), (away_en, away_cn)):
        if en and cn:
            out = re.sub(rf"\b{re.escape(en)}\b", cn, out, flags=re.I)
    return out


def _protect(text: str) -> tuple[str, dict[str, str]]:
    out = text
    mapping: dict[str, str] = {}
    idx = 0
    for pat, _repl in _load_protections():
        def _sub(m: re.Match[str]) -> str:
            nonlocal idx
            key = f"XZKEEP{idx}XZ"
            idx += 1
            mapping[key] = m.group(0)
            return key

        out = pat.sub(_sub, out)
    return out, mapping


def _unprotect(text: str, mapping: dict[str, str]) -> str:
    out = text
    for key, val in sorted(mapping.items(), key=lambda x: -len(x[0])):
        out = out.replace(key, val)
    return re.sub(r"XZKEEP\d+XZ", "", out)


def translate_en_to_zh(
    text: str,
    *,
    use_cache: bool = True,
    home_cn: str = "",
    away_cn: str = "",
    home_en: str = "",
    away_en: str = "",
) -> str:
    """Best-effort EN→ZH; keeps protected names, uses disk cache."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    curated = _curated_fifa_sentence(raw)
    if curated:
        return _polish_broken_zh(curated)
    raw = _pre_substitute_teams(
        raw, home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en,
    )
    glossed = _glossary_pass(raw)
    if not needs_zh_translate(glossed):
        return _polish_broken_zh(glossed)

    cache = _cache_load() if use_cache else {}
    ck = _cache_key(glossed)
    if use_cache and ck in cache:
        return _polish_broken_zh(cache[ck])

    protected, mapping = _protect(glossed)
    translated = protected
    try:
        import requests

        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": protected[:480], "langpair": "en|zh-CN"},
            timeout=18,
            headers={"User-Agent": "guess-you-like/1.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
        bit = str((payload.get("responseData") or {}).get("translatedText") or "").strip()
        if bit and bit.upper() != protected.upper():
            translated = bit
    except Exception as exc:
        log.debug("MyMemory translate failed: %s", exc)

    out = _unprotect(translated, mapping)
    out = _glossary_pass(out)
    if not _CJK.search(out):
        out = glossed
    out = _polish_broken_zh(out)
    if use_cache and out:
        cache[ck] = out
        _cache_save(cache)
    return out


def translate_list(
    items: list[str],
    *,
    home_cn: str = "",
    away_cn: str = "",
    home_en: str = "",
    away_en: str = "",
) -> list[str]:
    seen: dict[str, str] = {}
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if not s:
            continue
        if s in seen:
            out.append(seen[s])
            continue
        zh = translate_en_to_zh(
            s, home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en,
        )
        seen[s] = zh
        out.append(zh)
    return out


def _curated_fifa_sentence(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    for pat, zh in _FIFA_CURATED_SENTENCES:
        if re.search(pat, s, flags=re.I):
            return zh
    return ""


def _polish_broken_zh(text: str) -> str:
    out = str(text or "").strip()
    if not out:
        return out
    if re.search(r"日本也.*小组赛.*固", out):
        return "日本小组赛同样表现稳健。"
    if re.search(r"巴西队.*气缸|进入所有气缸", out):
        return "巴西队进入淘汰赛，状态火热、全线进攻。"
    for pat, repl in _BROKEN_ZH_FIXES:
        out = re.sub(pat, repl, out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ·，,。；;")
    return out


def _glossary_pass(text: str) -> str:
    out = str(text or "")
    merged = {**_STAGE_ZH, **_STADIUM_ZH, **_FOOTBALL_PHRASE_ZH}
    for en, zh in sorted(merged.items(), key=lambda x: -len(x[0])):
        out = re.sub(re.escape(en), zh, out, flags=re.I)
    return out


LOCALIZE_VERSION = 3

# 常见球员中文译名（世界杯报道常用叫法）
_PLAYER_ZH: dict[str, str] = {
    "Alisson": "阿利松",
    "Danilo": "达尼洛",
    "Marquinhos": "马尔基尼奥斯",
    "Gabriel Magalhaes": "加布里埃尔·马加良斯",
    "Gabriel Magalhães": "加布里埃尔·马加良斯",
    "Alex Sandro": "亚历克斯·桑德罗",
    "Bruno Guimaraes": "布鲁诺·吉马良斯",
    "Bruno Guimaraes": "布鲁诺·吉马良斯",
    "Casemiro": "卡塞米罗",
    "Lucas Paqueta": "卢卡斯·帕奎塔",
    "Lucas Paquetá": "卢卡斯·帕奎塔",
    "Rayan": "拉扬",
    "Matheus Cunha": "马特乌斯·库尼亚",
    "Vinicius Junior": "维尼修斯",
    "Vinicius Jr.": "维尼修斯",
    "Vinicius Jr": "维尼修斯",
    "Z.Suzuki": "铃木彩艳",
    "H. Ito": "伊藤洋辉",
    "Taniguchi": "谷口彰悟",
    "Tomiyasu": "富安健洋",
    "Doan": "堂安律",
    "Tanaka": "田中碧",
    "Sano": "佐野海舟",
    "Nakamura": "中村敬斗",
    "Maeda": "前田大然",
    "Kamada": "镰田大地",
    "Ueda": "上田绮世",
    "Raphinha": "拉菲尼亚",
    "Ko Itakura": "板仓滉",
    "Takefusa Kubo": "久保建英",
    "T. Kubo": "久保建英",
    "Vinícius Júnior": "维尼修斯",
    "Daichi Kamada": "镰田大地",
    "Ayase Ueda": "上田绮世",
}


def translate_player_name(name: str) -> str:
    """Player name → Chinese (glossary first, then free API + cache)."""
    n = re.sub(r"\u00a0", " ", str(name or "").strip())
    if not n:
        return n
    norm = re.sub(r"\s+", " ", n)
    low = norm.lower()
    for en, zh in _PLAYER_ZH.items():
        if en.lower() == low:
            return zh
    if _CJK.search(norm) and not needs_zh_translate(norm):
        return norm

    cache = _cache_load()
    ck = _cache_key(f"player:{low}")
    if ck in cache:
        return cache[ck]

    try:
        import requests

        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": norm[:120], "langpair": "en|zh-CN"},
            timeout=12,
            headers={"User-Agent": "guess-you-like/1.0"},
        )
        resp.raise_for_status()
        zh = str((resp.json().get("responseData") or {}).get("translatedText") or "").strip()
        if zh and _CJK.search(zh):
            cache[ck] = zh
            _cache_save(cache)
            return zh
    except Exception as exc:
        log.debug("player name translate failed %s: %s", norm, exc)
    return norm


def translate_lineup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        out.append({
            "label": str(row.get("label") or ""),
            "players": [translate_player_name(p) for p in (row.get("players") or [])],
        })
    return out


def stadium_to_zh(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    for en, zh in _STADIUM_ZH.items():
        if en.lower() == s.lower():
            return zh
    if _CJK.search(s):
        return s
    return translate_en_to_zh(s) or s


def stage_to_zh(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    for en, zh in _STAGE_ZH.items():
        if en.lower() == s.lower():
            return zh
    if _CJK.search(s):
        return s
    return translate_en_to_zh(s) or s


def localize_fifa_preview(
    preview: dict[str, Any],
    *,
    home_cn: str = "",
    away_cn: str = "",
) -> dict[str, Any]:
    """Add Chinese fields for poster display; idempotent."""
    p = dict(preview or {})
    if p.get("localized_zh") and p.get("localize_version") == LOCALIZE_VERSION:
        return p

    try:
        from fifa_preview import align_lineups_for_match, team_en_name, _parse_lineup_rows
    except Exception:
        align_lineups_for_match = None  # type: ignore
        _parse_lineup_rows = None  # type: ignore
        team_en_name = lambda x: x  # type: ignore

    try:
        home_en = team_en_name(home_cn) if home_cn else ""
        away_en = team_en_name(away_cn) if away_cn else ""
    except Exception:
        home_en = away_en = ""

    if not home_cn and p.get("home_cn"):
        home_cn = str(p.get("home_cn") or "")
    if not away_cn and p.get("away_cn"):
        away_cn = str(p.get("away_cn") or "")

    tkw = dict(home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en)

    by_team = dict(p.get("lineups_by_team") or {})
    if align_lineups_for_match and by_team and home_cn and away_cn:
        p["lineups"] = align_lineups_for_match(by_team, home_cn, away_cn)

    lineups = p.get("lineups") or {}
    if _parse_lineup_rows:
        rows_zh: dict[str, Any] = {}
        for side in ("home", "away"):
            xi = str(lineups.get(side) or "")
            if xi:
                rows_zh[side] = translate_lineup_rows(_parse_lineup_rows(xi))
        if rows_zh:
            p["lineups_rows_zh"] = rows_zh

    p["stadium_zh"] = stadium_to_zh(str(p.get("stadium") or ""))
    p["stage_zh"] = stage_to_zh(str(p.get("stage") or ""))

    mp = str(p.get("match_preview") or "").strip()
    if mp:
        p["match_preview_zh"] = translate_en_to_zh(mp, **tkw)

    sn = str(p.get("stadium_note") or "").strip()
    if sn:
        p["stadium_note_zh"] = translate_en_to_zh(sn, **tkw)

    notes = [str(x) for x in (p.get("key_player_notes") or []) if str(x).strip()]
    if notes:
        p["key_player_notes_zh"] = translate_list(notes, **tkw)

    kt = str(p.get("kickoff_times") or "").strip()
    if kt and needs_zh_translate(kt):
        p["kickoff_times_zh"] = translate_en_to_zh(kt, **tkw)

    title = str(p.get("article_title") or "").strip()
    if title and needs_zh_translate(title):
        p["article_title_zh"] = translate_en_to_zh(title, **tkw)

    p["localized_zh"] = True
    p["localize_version"] = LOCALIZE_VERSION
    p["localized_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return p


def ensure_localized_preview(
    preview: dict[str, Any] | None,
    *,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
) -> dict[str, Any] | None:
    if not preview:
        return None
    if preview.get("localized_zh") and preview.get("localize_version") == LOCALIZE_VERSION:
        return preview
    localized = localize_fifa_preview(
        preview,
        home_cn=str(preview.get("home_cn") or ""),
        away_cn=str(preview.get("away_cn") or ""),
    )
    if output_root and fixture_id and localized.get("localized_zh"):
        try:
            from fifa_preview import save_fifa_preview

            save_fifa_preview(output_root, fixture_id, localized)
        except Exception as exc:
            log.debug("save localized preview skipped: %s", exc)
    return localized


def pick_zh(preview: dict[str, Any], field: str) -> str:
    return str(preview.get(f"{field}_zh") or preview.get(field) or "").strip()
