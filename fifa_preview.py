"""Fetch FIFA.com official match preview articles (lineups, stadium, style notes)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from match_agents.storage import match_agent_dir

log = logging.getLogger(__name__)

FIFA_API = "https://cxm-api.fifa.com/fifaplusweb/api"
FIFA_ARTICLE_PREFIX = (
    "/en/tournaments/mens/worldcup/canadamexicousa2026/articles"
)
PREVIEW_FILE = "fifa_preview.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_LINEUP_HEADING = re.compile(
    r"(?P<team>.+?)\s+possible\s+starting\s+XI",
    re.I,
)
_GOAL_NOTE = re.compile(
    r"([A-Z][A-Za-z\u00c0-\u024f.'\-]+(?:\s+[A-Z][A-Za-z\u00c0-\u024f.'\-]+)*"
    r"(?:\s+Jr\.?)?)"
    r".{0,40}?(?:scored|notching|goals?|pair of goals)",
    re.I,
)


def _session():
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": _USER_AGENT, "Accept": "application/json"})
    return s


def _load_team_en_map() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return out
    for cn, aliases in (data.get("aliases") or {}).items():
        for alias in aliases or []:
            if isinstance(alias, str) and alias.isascii() and len(alias) > 2:
                out[cn] = alias
                break
        if cn not in out:
            out[cn] = cn
    return out


_TEAM_EN = _load_team_en_map()


def team_en_name(cn: str) -> str:
    from team_recent_form import canonical_team

    key = canonical_team(str(cn or "").strip())
    return _TEAM_EN.get(key, key or str(cn or "").strip())


def _slug_part(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s.replace("cote-d-ivoire", "ivory-coast")


def preview_path(output_root: str | Path, fixture_id: str) -> Path:
    return match_agent_dir(output_root, fixture_id) / PREVIEW_FILE


def load_fifa_preview(
    output_root: str | Path | None,
    fixture_id: str | None,
) -> dict[str, Any] | None:
    if not output_root or not fixture_id:
        return None
    path = preview_path(output_root, fixture_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("读取 FIFA 预览失败 %s: %s", path, exc)
        return None


def save_fifa_preview(
    output_root: str | Path,
    fixture_id: str,
    payload: dict[str, Any],
) -> Path:
    path = preview_path(output_root, fixture_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _richtext_plain(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    if node.get("nodeType") == "text":
        return str(node.get("value") or "")
    parts: list[str] = []
    for child in node.get("content") or []:
        parts.append(_richtext_plain(child))
    return "".join(parts)


def _walk_richtext(doc: dict[str, Any] | None) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for node in (doc or {}).get("content") or []:
        ntype = str(node.get("nodeType") or "")
        text = _richtext_plain(node).strip()
        if ntype.startswith("heading") and text:
            blocks.append({"type": "heading", "level": ntype, "text": text})
        elif ntype == "paragraph" and text:
            blocks.append({"type": "paragraph", "text": text})
    return blocks


def _extract_lineups(blocks: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, block in enumerate(blocks):
        if block.get("type") != "heading":
            continue
        m = _LINEUP_HEADING.search(str(block.get("text") or ""))
        if not m:
            continue
        team = m.group("team").strip()
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt and nxt.get("type") == "paragraph":
            out[team] = str(nxt.get("text") or "").strip()
    return out


def _section_text(blocks: list[dict[str, str]], heading: str) -> str:
    target = heading.lower()
    parts: list[str] = []
    capture = False
    for block in blocks:
        if block.get("type") == "heading":
            text = str(block.get("text") or "").strip()
            if text.lower() == target:
                capture = True
                continue
            if capture and block.get("level") in ("heading-3", "heading-2"):
                break
            if capture and str(block.get("level") or "").startswith("heading"):
                lvl = block.get("level") or ""
                if lvl in ("heading-4", "heading-5"):
                    continue
                break
        if capture and block.get("type") == "paragraph":
            parts.append(str(block.get("text") or "").strip())
    return " ".join(x for x in parts if x)


def _key_player_notes(preview: str, lineups: dict[str, str]) -> list[str]:
    notes: list[str] = []
    for m in _GOAL_NOTE.finditer(preview or ""):
        frag = m.group(0).strip()
        if frag and frag not in notes:
            notes.append(frag[:100])
    if notes:
        return notes[:4]
    for lu in lineups.values():
        players = [p.strip() for p in re.split(r"[;,]", lu) if p.strip()]
        if len(players) >= 3:
            notes.append(f"预测首发含 {', '.join(players[-3:])}")
    return notes[:4]


def _parse_stadium_from_blocks(blocks: list[dict[str, str]]) -> str:
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "")
        if "|" in text and re.search(r"Stadium|Arena|Field", text, re.I):
            parts = [p.strip() for p in text.split("|")]
            if len(parts) >= 2:
                return parts[-1]
    return ""


def _tags_from_page(page: dict[str, Any]) -> dict[str, Any]:
    stadium = ""
    match_id = ""
    teams: list[str] = []
    for tag in page.get("tags") or []:
        cat = str(tag.get("sourceCategory") or "")
        title = str(tag.get("title") or "").strip()
        tid = str(tag.get("id") or "")
        if cat == "Stadium" and title:
            stadium = title
        elif cat == "Match" and tid:
            match_id = tid
        elif cat == "Team" and title:
            teams.append(title)
    return {"stadium": stadium, "match_id": match_id, "teams": teams}


def fetch_fifa_page(relative_path: str) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    path = relative_path if relative_path.startswith("/") else f"/{relative_path}"
    url = f"{FIFA_API}/pages{path}"
    try:
        resp = _session().get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        logs.append(f"FIFA page OK: {path}")
        return data, logs
    except Exception as exc:
        logs.append(f"FIFA page 失败 {path}: {exc}")
        return {}, logs


def fetch_fifa_article_section(entry_id: str, *, locale: str = "en") -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    url = f"{FIFA_API}/sections/article/{entry_id}?locale={locale}"
    try:
        resp = _session().get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        logs.append(f"FIFA article section OK: {entry_id}")
        return data, logs
    except Exception as exc:
        logs.append(f"FIFA article 失败 {entry_id}: {exc}")
        return {}, logs


def _article_entry_id(page: dict[str, Any]) -> str:
    for sec in page.get("sections") or []:
        if str(sec.get("entryType") or "") == "article":
            eid = str(sec.get("entryId") or "")
            if eid:
                return eid
    return ""


def _page_matches_teams(page: dict[str, Any], home_en: str, away_en: str) -> bool:
    meta = _tags_from_page(page)
    teams = {t.lower() for t in meta.get("teams") or []}
    need = {home_en.lower(), away_en.lower()}
    return need.issubset(teams) if teams else False


def discover_article_path(home_cn: str, away_cn: str, *, use_search: bool = True) -> tuple[str, list[str]]:
    """Return relative article path like /en/tournaments/.../articles/slug."""
    logs: list[str] = []
    home_en = team_en_name(home_cn)
    away_en = team_en_name(away_cn)
    if not home_en or not away_en:
        logs.append("队名无法映射为英文，跳过 FIFA 预览")
        return "", logs

    candidates = [
        f"{FIFA_ARTICLE_PREFIX}/{_slug_part(home_en)}-{_slug_part(away_en)}-live-stream-team-news-tickets",
        f"{FIFA_ARTICLE_PREFIX}/{_slug_part(away_en)}-{_slug_part(home_en)}-live-stream-team-news-tickets",
    ]
    for rel in candidates:
        page, plogs = fetch_fifa_page(rel)
        logs.extend(plogs)
        if page and _page_matches_teams(page, home_en, away_en):
            logs.append(f"命中 FIFA 预览 slug: {rel.split('/')[-1]}")
            return rel, logs

    if not use_search:
        logs.append("直链 slug 未命中，且未启用搜索")
        return "", logs

    from match_agents.web_lookup import search_web

    q = f"site:fifa.com/canadamexicousa2026/articles {home_en} {away_en} team news tickets"
    hits, slogs = search_web(q, max_results=5)
    logs.extend(slogs)
    for hit in hits:
        url = str(hit.get("url") or "")
        m = re.search(r"(/en/tournaments/mens/worldcup/canadamexicousa2026/articles/[a-z0-9-]+)", url)
        if not m:
            continue
        rel = m.group(1)
        page, plogs = fetch_fifa_page(rel)
        logs.extend(plogs)
        if page and _page_matches_teams(page, home_en, away_en):
            logs.append(f"搜索命中 FIFA 预览: {rel.split('/')[-1]}")
            return rel, logs
    logs.append("未找到匹配的 FIFA 官方预览文章")
    return "", logs


def parse_fifa_preview(page: dict[str, Any], article: dict[str, Any], *, article_path: str = "") -> dict[str, Any]:
    blocks = _walk_richtext(article.get("richtext") or {})
    tag_meta = _tags_from_page(page)
    lineups_raw = _extract_lineups(blocks)
    preview = _section_text(blocks, "The match")
    stadium_blurb = _section_text(blocks, "Houston Stadium")
    if not stadium_blurb:
        for block in blocks:
            if block.get("type") == "heading" and re.search(r"Stadium|Arena", str(block.get("text") or ""), re.I):
                idx = blocks.index(block)
                nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
                if nxt and nxt.get("type") == "paragraph":
                    stadium_blurb = str(nxt.get("text") or "")
                break

    lineups_by_team: dict[str, str] = dict(lineups_raw)

    match_centre = ""
    for block in blocks:
        if block.get("type") == "heading" and " v " in str(block.get("text") or "").lower():
            pass
    for node in (article.get("richtext") or {}).get("content") or []:
        for child in node.get("content") or []:
            if child.get("nodeType") == "hyperlink":
                uri = str((child.get("data") or {}).get("uri") or "")
                if "/match-centre/match/" in uri:
                    match_centre = uri
                    break

    return {
        "article_title": str(article.get("articleTitle") or page.get("meta", {}).get("title") or ""),
        "article_published": str(article.get("articlePublishedDate") or ""),
        "source_url": f"https://www.fifa.com{article_path or page.get('relativeUrl') or ''}",
        "article_path": article_path or str(page.get("relativeUrl") or ""),
        "stadium": tag_meta.get("stadium") or _parse_stadium_from_blocks(blocks),
        "stage": _section_text(blocks, "Round of 32") or next(
            (b["text"] for b in blocks if b.get("type") == "heading" and b.get("level") == "heading-3"),
            "",
        ),
        "kickoff_line": next(
            (b["text"] for b in blocks if b.get("type") == "paragraph" and "|" in b.get("text", "") and "Stadium" in b.get("text", "")),
            "",
        ),
        "kickoff_times": _section_text(blocks, "Kick-off time") or next(
            (
                b["text"]
                for b in blocks
                if b.get("type") == "paragraph"
                and re.search(r"\(\w+\)", b.get("text", ""))
                and ":" in b.get("text", "")
            ),
            "",
        ),
        "match_id": tag_meta.get("match_id") or "",
        "match_centre_url": match_centre,
        "teams_en": tag_meta.get("teams") or [],
        "match_preview": preview,
        "stadium_note": stadium_blurb[:400] if stadium_blurb else "",
        "lineups_by_team": lineups_by_team,
        "lineups": {},
        "key_player_notes": _key_player_notes(preview, lineups_raw),
    }


def align_lineups_for_match(
    lineups_by_team: dict[str, str],
    home_cn: str,
    away_cn: str,
) -> dict[str, str]:
    """Map FIFA team-name keys to match home/away (index order, not FIFA tag order)."""
    home_en = team_en_name(home_cn)
    away_en = team_en_name(away_cn)
    home_xi = ""
    away_xi = ""
    for team, xi in (lineups_by_team or {}).items():
        tl = str(team).strip().lower()
        if tl in ("home_en", "away_en", "home", "away"):
            continue
        if home_en and tl == home_en.lower():
            home_xi = str(xi or "")
        elif away_en and tl == away_en.lower():
            away_xi = str(xi or "")
    return {"home": home_xi, "away": away_xi}


def fetch_fifa_preview_by_path(relative_path: str) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    page, plogs = fetch_fifa_page(relative_path)
    logs.extend(plogs)
    if not page:
        return {}, logs
    entry_id = _article_entry_id(page)
    if not entry_id:
        logs.append("页面无 article section")
        return {}, logs
    article, alogs = fetch_fifa_article_section(entry_id)
    logs.extend(alogs)
    if not article:
        return {}, logs
    parsed = parse_fifa_preview(page, article, article_path=relative_path)
    parsed["fetch_log"] = logs
    parsed["fetched_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return parsed, logs


def fetch_fifa_preview_for_match(
    home_cn: str,
    away_cn: str,
    *,
    use_search: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    rel, dlogs = discover_article_path(home_cn, away_cn, use_search=use_search)
    logs.extend(dlogs)
    if not rel:
        return {}, logs
    parsed, flogs = fetch_fifa_preview_by_path(rel)
    logs.extend(flogs)
    if parsed:
        parsed["home_cn"] = home_cn
        parsed["away_cn"] = away_cn
        by_team = dict(parsed.get("lineups_by_team") or {})
        if not by_team:
            for key, xi in (parsed.get("lineups") or {}).items():
                kl = str(key).lower()
                if kl not in ("home", "away", "home_en", "away_en"):
                    by_team[str(key)] = xi
            parsed["lineups_by_team"] = by_team
        parsed["lineups"] = align_lineups_for_match(by_team, home_cn, away_cn)
        parsed["fetch_log"] = logs
    return parsed, logs


def get_or_fetch_fifa_preview(
    home_cn: str,
    away_cn: str,
    fixture_id: str,
    output_root: str | Path,
    *,
    force: bool = False,
    use_search: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    logs: list[str] = []
    if not force:
        cached = load_fifa_preview(output_root, fixture_id)
        if cached:
            by_team = cached.get("lineups_by_team") or {}
            lineups = cached.get("lineups") or {}
            if not by_team and not str(lineups.get("home") or "").strip():
                logs.append("缓存缺少 FIFA 首发，自动重新抓取")
                force = True
            else:
                from fifa_translate import ensure_localized_preview

                cached = ensure_localized_preview(
                    cached, output_root=output_root, fixture_id=fixture_id,
                ) or cached
                logs.append("使用已缓存 FIFA 预览")
                return cached, logs
    data, flogs = fetch_fifa_preview_for_match(home_cn, away_cn, use_search=use_search)
    logs.extend(flogs)
    if not data:
        cached = load_fifa_preview(output_root, fixture_id)
        if cached:
            from fifa_translate import ensure_localized_preview

            cached = ensure_localized_preview(
                cached, output_root=output_root, fixture_id=fixture_id,
            )
        return cached, logs
    data["fixture_id"] = str(fixture_id)
    from fifa_translate import localize_fifa_preview

    data = localize_fifa_preview(data, home_cn=home_cn, away_cn=away_cn)
    logs.append("已翻译为中文")
    save_fifa_preview(output_root, fixture_id, data)
    logs.append(f"已保存 {PREVIEW_FILE}")
    return data, logs


def _compact_lineup(xi: str, *, max_len: int = 88) -> str:
    s = re.sub(r"\s+", " ", str(xi or "").strip())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


_LINEUP_ROW_LABELS = ("门将", "后卫", "中场", "前锋")


def _parse_lineup_rows(xi: str) -> list[dict[str, Any]]:
    """Split FIFA possible XI string into GK/DEF/MID/FWD rows."""
    raw = re.sub(r"\u00a0", " ", str(xi or "")).strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    rows: list[dict[str, Any]] = []
    for i, part in enumerate(parts[:4]):
        players = [x.strip() for x in part.split(",") if x.strip()]
        if not players:
            continue
        rows.append({
            "label": _LINEUP_ROW_LABELS[i] if i < len(_LINEUP_ROW_LABELS) else f"第{i + 1}线",
            "players": players,
        })
    if not rows and raw:
        rows.append({"label": "预测首发", "players": [raw]})
    return rows


def _lineup_player_names(xi: str) -> list[str]:
    out: list[str] = []
    for row in _parse_lineup_rows(xi):
        out.extend(row.get("players") or [])
    if not out and xi:
        out = [p.strip() for p in re.split(r"[,;]", xi) if p.strip()]
    return out


def _player_token_match(player: str, text: str) -> bool:
    p = str(player or "").strip()
    if not p or not text:
        return False
    tl = text.lower()
    if p.lower() in tl:
        return True
    for part in p.replace(".", " ").split():
        if len(part) >= 3 and part.lower() in tl:
            return True
    return False


def _split_notes_by_players(
    notes: list[str],
    home_players: list[str],
    away_players: list[str],
) -> tuple[list[str], list[str]]:
    home_out: list[str] = []
    away_out: list[str] = []
    for note in notes:
        text = str(note or "").strip()
        if not text:
            continue
        h = any(_player_token_match(p, text) for p in home_players)
        a = any(_player_token_match(p, text) for p in away_players)
        if h and not a:
            home_out.append(text[:120])
        elif a and not h:
            away_out.append(text[:120])
        elif h and a:
            home_out.append(text[:120])
            away_out.append(text[:120])
    return home_out, away_out


def _highlights_from_preview(
    preview: str,
    players: list[str],
    *,
    limit: int = 3,
) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"(?<=[.!?。！？])\s+", str(preview or "").strip()):
        c = chunk.strip()
        if len(c) < 20:
            continue
        if any(_player_token_match(p, c) for p in players):
            out.append(c[:120])
        if len(out) >= limit:
            break
    return out


def _fallback_key_players(xi: str, *, limit: int = 3) -> list[str]:
    players = _lineup_player_names(xi)
    if not players:
        return []
    stars = players[-3:] if len(players) >= 3 else players
    return [f"FIFA 预测关注：{'、'.join(stars[:limit])}"]


def _split_notes_by_team(
    notes: list[str],
    *,
    home_cn: str,
    away_cn: str,
    home_en: str,
    away_en: str,
) -> tuple[list[str], list[str]]:
    home_out: list[str] = []
    away_out: list[str] = []
    for note in notes:
        text = str(note or "").strip()
        if not text:
            continue
        low = text.lower()
        home_hit = home_cn in text or (home_en and home_en.lower() in low)
        away_hit = away_cn in text or (away_en and away_en.lower() in low)
        if home_hit and not away_hit:
            home_out.append(text[:120])
        elif away_hit and not home_hit:
            away_out.append(text[:120])
        elif home_hit and away_hit:
            home_out.append(text[:120])
            away_out.append(text[:120])
    return home_out, away_out


def _preview_clauses(preview: str) -> list[str]:
    """Split FIFA preview into team-scoped clauses (handles Chinese comma-only text)."""
    text = str(preview or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    for part in re.split(r"(?<=[.!?。！？])\s+", text):
        part = part.strip()
        if not part:
            continue
        if re.search(r"[，,；;]", part) and len(part) > 36:
            chunks.extend(p.strip() for p in re.split(r"[，,；;]", part) if p.strip())
        else:
            chunks.append(part)
    return chunks


def _team_text_hits(
    text: str,
    *,
    home_cn: str,
    away_cn: str,
    home_en: str,
    away_en: str,
) -> tuple[bool, bool]:
    low = str(text or "").lower()
    home_hit = (
        home_cn in text
        or (home_en and home_en.lower() in low)
        or "seleção" in low
        or " seleç" in low
        or "巴西队" in text
    )
    away_hit = away_cn in text or (away_en and away_en.lower() in low)
    return home_hit, away_hit


def _preview_team_notes(
    preview: str,
    *,
    home_cn: str,
    away_cn: str,
    home_en: str,
    away_en: str,
    limit: int = 3,
) -> tuple[list[str], list[str]]:
    """Assign match-preview sentences to each team."""
    home_notes: list[str] = []
    away_notes: list[str] = []
    for chunk in _preview_clauses(preview):
        c = chunk.strip()
        if len(c) < 12:
            continue
        home_hit, away_hit = _team_text_hits(
            c, home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en,
        )
        if home_hit and not away_hit:
            home_notes.append(c[:120])
        elif away_hit and not home_hit:
            away_notes.append(c[:120])
        if len(home_notes) >= limit and len(away_notes) >= limit:
            break
    return home_notes[:limit], away_notes[:limit]


def _team_side_module(
    *,
    team_cn: str,
    key_players: list[str],
    tactics_lines: list[str],
    lineup_rows: list[dict[str, Any]],
    injuries: list[str],
) -> dict[str, Any]:
    kp = [_sanitize_fifa_line(x) for x in key_players[:4] if _sanitize_fifa_line(x)]
    tac = [_sanitize_fifa_line(x) for x in tactics_lines[:3] if _sanitize_fifa_line(x)]
    return {
        "team": team_cn,
        "key_players": kp,
        "tactics_lines": tac,
        "lineup_rows": lineup_rows,
        "injuries": injuries[:4],
        "has_lineup": bool(lineup_rows),
        "has_key_players": bool(kp),
        "has_tactics": bool(tac),
        "has_injuries": bool(injuries),
    }


def _sanitize_fifa_line(text: str) -> str:
    s = re.sub(r"\u00a0", " ", str(text or "").strip())
    if not s:
        return ""
    if re.search(r"Super Bowl|NFL|MLS|opened in|Host City", s, re.I):
        return ""
    if re.search(r"\d+\s*[-:：]\s*\d+", s):
        s = re.sub(r"\d+\s*[-:：]\s*\d+", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip(" ·，,；;。 ")
        if len(s) < 8:
            return ""
    for pat in (r"竞彩|盘口|赔率|亚盘|欧赔|让球|购彩|体彩|下注|串关", r"主胜|客胜"):
        if re.search(pat, s):
            s = re.sub(r"主胜", "主队机会", s)
            s = re.sub(r"客胜", "客队机会", s)
            s = re.sub(pat, "", s, flags=re.I)
    return s[:120].strip()


def viewing_notes_fifa_overlay(
    preview: dict[str, Any] | None,
    *,
    home_cn: str,
    away_cn: str,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
) -> dict[str, Any]:
    """Map FIFA preview JSON to per-team viewing-notes modules (Chinese first)."""
    if not preview:
        return {}
    try:
        from fifa_translate import ensure_localized_preview, pick_zh, stadium_to_zh

        preview = ensure_localized_preview(
            preview, output_root=output_root, fixture_id=fixture_id,
        ) or preview
    except Exception as exc:
        log.debug("FIFA localize skipped: %s", exc)

        def pick_zh(p: dict[str, Any], field: str) -> str:
            return str(p.get(f"{field}_zh") or p.get(field) or "").strip()

        def stadium_to_zh(name: str) -> str:
            return str(name or "").strip()

    lineups = preview.get("lineups") or {}
    by_team = preview.get("lineups_by_team") or {}
    if by_team and (not lineups.get("home") or not lineups.get("away")):
        lineups = align_lineups_for_match(by_team, home_cn, away_cn)
    home_xi = str(lineups.get("home") or "")
    away_xi = str(lineups.get("away") or "")

    rows_zh = preview.get("lineups_rows_zh") or {}
    home_rows = rows_zh.get("home") or []
    away_rows = rows_zh.get("away") or []
    if not home_rows and home_xi:
        try:
            from fifa_translate import translate_lineup_rows

            home_rows = translate_lineup_rows(_parse_lineup_rows(home_xi))
        except Exception:
            home_rows = _parse_lineup_rows(home_xi)
    if not away_rows and away_xi:
        try:
            from fifa_translate import translate_lineup_rows

            away_rows = translate_lineup_rows(_parse_lineup_rows(away_xi))
        except Exception:
            away_rows = _parse_lineup_rows(away_xi)

    home_en = team_en_name(home_cn)
    away_en = team_en_name(away_cn)
    home_pl = _lineup_player_names(home_xi)
    away_pl = _lineup_player_names(away_xi)
    match_preview = pick_zh(preview, "match_preview") or str(preview.get("match_preview") or "")
    notes_raw = preview.get("key_player_notes_zh") or preview.get("key_player_notes") or []
    kp_home, kp_away = _split_notes_by_players(notes_raw, home_pl, away_pl)
    if not kp_home and not kp_away:
        notes_en = preview.get("key_player_notes") or []
        kp_home, kp_away = _split_notes_by_team(
            notes_en,
            home_cn=home_cn,
            away_cn=away_cn,
            home_en=home_en,
            away_en=away_en,
        )
    if not kp_home:
        kp_home = _highlights_from_preview(match_preview, home_pl, limit=3)
    if not kp_away:
        kp_away = _highlights_from_preview(match_preview, away_pl, limit=3)
    if not kp_home and home_xi:
        kp_home = _fallback_key_players(home_xi)
    if not kp_away and away_xi:
        kp_away = _fallback_key_players(away_xi)
    en_preview = str(preview.get("match_preview") or "")
    tac_home, tac_away = _preview_team_notes(
        en_preview,
        home_cn=home_cn,
        away_cn=away_cn,
        home_en=home_en,
        away_en=away_en,
    )
    if not tac_home and not tac_away:
        tac_home, tac_away = _preview_team_notes(
            match_preview,
            home_cn=home_cn,
            away_cn=away_cn,
            home_en=home_en,
            away_en=away_en,
        )

    try:
        from fifa_translate import needs_zh_translate, translate_en_to_zh

        tkw = dict(home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en)

        def _maybe_zh(lines: list[str]) -> list[str]:
            out: list[str] = []
            for x in lines[:3]:
                bit = translate_en_to_zh(x, **tkw) if needs_zh_translate(x) else x
                clean = _sanitize_fifa_line(bit)
                if clean:
                    out.append(clean)
            return out

        kp_home = _maybe_zh(kp_home)
        kp_away = _maybe_zh(kp_away)
        tac_home = _maybe_zh(tac_home[:2])
        tac_away = _maybe_zh(tac_away[:2])
    except Exception as exc:
        log.debug("team notes translate skipped: %s", exc)
        kp_home = [_sanitize_fifa_line(x) for x in kp_home[:3] if _sanitize_fifa_line(x)]
        kp_away = [_sanitize_fifa_line(x) for x in kp_away[:3] if _sanitize_fifa_line(x)]
        tac_home = [_sanitize_fifa_line(x) for x in tac_home[:2] if _sanitize_fifa_line(x)]
        tac_away = [_sanitize_fifa_line(x) for x in tac_away[:2] if _sanitize_fifa_line(x)]

    stadium = stadium_to_zh(str(preview.get("stadium_zh") or preview.get("stadium") or ""))
    kickoff_extra = f" · {stadium}（FIFA官方）" if stadium else ""

    return {
        "team_modules": {
            "home": _team_side_module(
                team_cn=home_cn,
                key_players=kp_home,
                tactics_lines=tac_home,
                lineup_rows=home_rows,
                injuries=[],
            ),
            "away": _team_side_module(
                team_cn=away_cn,
                key_players=kp_away,
                tactics_lines=tac_away,
                lineup_rows=away_rows,
                injuries=[],
            ),
        },
        "kickoff_extra": kickoff_extra,
        "stadium": stadium,
        "source_url": preview.get("source_url") or "",
        "fetched_at": preview.get("fetched_at") or "",
    }
