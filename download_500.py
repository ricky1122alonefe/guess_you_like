#!/usr/bin/env python3
"""Download live Asian/European odds Excel exports from odds.500.com."""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Collection, Iterable

import requests
from bs4 import BeautifulSoup

from time_utils import BEIJING, now_beijing, to_beijing

BASE = "https://odds.500.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 60
# live.500.com 赛程表第 2 列；默认只抓世界杯，避免芬超等联赛混入
DEFAULT_LEAGUES: tuple[str, ...] = ("世界杯",)


@dataclass
class MatchFixture:
    fixture_id: str
    home: str = ""
    away: str = ""
    label: str = ""
    kickoff: datetime | None = None
    order_id: str = ""
    match_num: str = ""
    league: str = ""
    status_phase: str = ""  # upcoming | live | finished
    live_score: str = ""
    status_label: str = ""

    @property
    def kickoff_label(self) -> str:
        if not self.kickoff:
            return "—"
        return self.kickoff.strftime("%m-%d %H:%M")

    @property
    def base_name(self) -> str:
        if self.home and self.away:
            return f"{self.home}VS{self.away}"
        if self.label:
            return re.sub(r"\(.*?\)", "", self.label).strip()
        return f"match_{self.fixture_id}"

    @property
    def ah_filename(self) -> str:
        return f"{self.base_name}(亚盘).xls"

    @property
    def eu_filename(self) -> str:
        return f"{self.base_name}(世界杯)欧洲数据.xls"


class Download500Error(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _decode(content: bytes) -> str:
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("gb18030", errors="replace")


def extract_fixture_id(url_or_id: str) -> str:
    text = str(url_or_id).strip()
    if text.isdigit():
        return text
    m = re.search(r"(?:youliao|yazhi|ouzhi)-(\d+)\.shtml", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{6,})", text)
    if m:
        return m.group(1)
    raise Download500Error(f"无法解析比赛 ID: {url_or_id}")


def _parse_kickoff(text: str, ref: datetime | None = None) -> datetime | None:
    """Parse '06-14 03:00' from live.500.com row text (Asia/Shanghai)."""
    ref = to_beijing(ref or now_beijing())
    m = re.search(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    hour, minute = int(m.group(3)), int(m.group(4))
    dt = datetime(ref.year, month, day, hour, minute, tzinfo=BEIJING)
    if dt < ref - timedelta(days=180):
        dt = dt.replace(year=ref.year + 1)
    return dt


def _parse_match_score(text: str) -> str:
    """Extract live score; skip kickoff dates like 06-21."""
    for m in re.finditer(r"(\d+)\s*-\s*(\d+)", text):
        h, a = int(m.group(1)), int(m.group(2))
        if 1 <= h <= 12 and 13 <= a <= 31:
            continue
        if h > 20 or a > 20:
            continue
        return f"{h}-{a}"
    return ""


def _parse_row_status(tr) -> dict[str, str]:
    """Parse live.500 tr: 未 / 完 / score / minute → phase for dashboard."""
    if tr is None:
        return {}
    parts = [p.strip() for p in tr.get_text("|", strip=True).split("|") if p.strip()]
    text = "|".join(parts)

    if any(p == "完" for p in parts):
        score = _parse_match_score(text)
        return {"phase": "finished", "label": "完场", "score": score}

    if any(p == "未" for p in parts):
        return {"phase": "upcoming", "label": "未开赛"}

    min_m = re.search(r"(\d+(?:\+\d+)?)'", text)
    score = _parse_match_score(text)
    if min_m:
        return {
            "phase": "live",
            "label": f"{min_m.group(1)}'",
            "score": score,
            "minute": min_m.group(1),
        }

    if score and not any(p in ("胜", "负", "平") for p in parts):
        return {
            "phase": "live",
            "label": "进行中",
            "score": score,
        }

    return {}


def _parse_teams_from_row(text: str) -> tuple[str, str]:
    """Best-effort parse home/away from live.500 tr text."""
    parts = [p.strip() for p in text.split("|") if p.strip()]
    # Skip metadata cells until we hit team-like tokens (non-numeric, not handicap)
    teams: list[str] = []
    skip = {
        "世界杯", "未", "析", "亚", "欧", "推荐", "置顶", "-",
    }
    for p in parts:
        if re.match(r"^周[一二三四五六日天]", p):
            continue
        if re.match(r"^第\d+轮$", p):
            continue
        if re.match(r"^\d{2}-\d{2}\s+\d{2}:\d{2}$", p):
            continue
        if re.match(r"^\[\d+\]$", p):
            continue
        if p in skip:
            continue
        if re.match(r"^\([+\-]\d+\)$", p):
            continue
        if re.search(r"球|/|平手|受让", p) and len(p) < 12:
            continue
        if len(p) >= 2 and not p.isdigit():
            teams.append(re.sub(r"\[\d+\]", "", p).strip())
        if len(teams) >= 2:
            break
    if len(teams) >= 2:
        return teams[0], teams[1]
    return "", ""


def _parse_league_from_tr(tr) -> str:
    if tr is None:
        return ""
    tds = tr.find_all("td")
    if len(tds) > 1:
        return tds[1].get_text(strip=True)
    return ""


def _within_days(kickoff: datetime | None, *, days: float, now: datetime | None = None) -> bool:
    if kickoff is None:
        return False
    now = to_beijing(now or now_beijing())
    ko = to_beijing(kickoff)
    # Include about-to-start / in-play (30 min grace); exclude far-future fixtures.
    return (ko >= now - timedelta(minutes=30)) and (ko <= now + timedelta(days=days))


def _parse_teams_from_title(title: str) -> tuple[str, str]:
    m = re.search(r"^(.+?)VS(.+?)(?:\(|$|-)", title)
    if not m:
        return "", ""
    return m.group(1).strip(), m.group(2).strip()


def fetch_match_info(session: requests.Session, fixture_id: str) -> MatchFixture:
    """Resolve team names from analysis/odds pages."""
    fid = extract_fixture_id(fixture_id)
    ah_url = f"{BASE}/fenxi/yazhi-{fid}.shtml"
    resp = session.get(ah_url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    html = _decode(resp.content)
    soup = BeautifulSoup(html, "html.parser")

    name_inp = soup.select_one('form#plform input[name="name"]')
    label = name_inp["value"] if name_inp and name_inp.get("value") else ""

    title = soup.title.get_text(strip=True) if soup.title else ""
    home, away = _parse_teams_from_title(title)
    if not home and label:
        home, away = _parse_teams_from_title(label + "(x)")

    return MatchFixture(fixture_id=fid, home=home, away=away, label=label)


def _serialize_xls_table(soup: BeautifulSoup) -> dict[str, list[str]]:
    """Mirror odds.500.com downpl JS: collect [xls=header|row|footer] cells."""
    datalist: dict[str, list[str]] = {"header": [], "row": [], "footer": []}
    for el in soup.find_all(attrs={"xls": True}):
        in_name = el["xls"]
        if in_name not in datalist:
            continue

        td: list[str] = []
        td1: list[str] = []
        for cell in el.find_all(attrs={"row": True}):
            style = (cell.get("style") or "").lower().replace(" ", "")
            if "display:none" in style:
                continue
            text = cell.get_text(strip=True).replace("↑", "").replace("↓", "")
            classes = " ".join(cell.get("class") or [])
            parent_classes = ""
            if cell.parent and hasattr(cell.parent, "get"):
                parent_classes = " ".join(cell.parent.get("class") or [])

            if "td_show_cp" in classes or "td_show_cp" in parent_classes:
                td1.append(text)
            else:
                td.append(text)

        if td1:
            if td:
                td1.insert(0, td[0])
            datalist[in_name].append("|".join(td1))
        elif td:
            datalist[in_name].append("|".join(td))
    return datalist


def download_asian_handicap_xls(
    session: requests.Session,
    fixture_id: str,
    dest: Path,
) -> Path:
    fid = extract_fixture_id(fixture_id)
    page_url = f"{BASE}/fenxi/yazhi-{fid}.shtml"
    resp = session.get(page_url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    html = _decode(resp.content)
    soup = BeautifulSoup(html, "html.parser")

    name_inp = soup.select_one('form#plform input[name="name"]')
    if not name_inp or not name_inp.get("value"):
        raise Download500Error(f"亚盘页未找到下载表单: {page_url}")
    name = name_inp["value"]

    datalist = _serialize_xls_table(soup)
    if not datalist["row"]:
        raise Download500Error(f"亚盘页无赔率行数据: {page_url}")

    data: dict[str, str] = {"name": name}
    for key in ("header", "row", "footer"):
        if datalist[key]:
            data[key] = "$".join(datalist[key])

    post = session.post(
        f"{BASE}/fenxi1/xls.php",
        data=data,
        headers={"Referer": page_url},
        timeout=DEFAULT_TIMEOUT,
    )
    post.raise_for_status()
    _ensure_xls_bytes(post.content, "亚盘")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(post.content)
    return dest


def download_european_odds_xls(
    session: requests.Session,
    fixture_id: str,
    dest: Path,
) -> Path:
    fid = extract_fixture_id(fixture_id)
    page_url = f"{BASE}/fenxi/ouzhi-{fid}.shtml"
    resp = session.get(page_url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()

    data = {
        "fixtureid": fid,
        "excelst": "1",
        "style": "0",
        "ctype": "1",
        "dcid": "",
        "scid": "",
        "r": "1",
    }
    post = session.post(
        f"{BASE}/fenxi/europe_xls.php",
        data=data,
        headers={"Referer": page_url},
        timeout=DEFAULT_TIMEOUT,
    )
    post.raise_for_status()
    _ensure_xls_bytes(post.content, "欧赔")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(post.content)
    return dest


def _ensure_xls_bytes(content: bytes, label: str) -> None:
    if len(content) < 512:
        raise Download500Error(f"{label} 下载失败（响应过短）: {content[:80]!r}")
    if content[:4] != b"\xd0\xcf\x11\xe0":
        text = content.decode("utf-8", errors="replace")
        raise Download500Error(f"{label} 下载失败（非 Excel）: {text[:200]}")


def fetch_live_fixtures(
    session: requests.Session | None = None,
    *,
    within_days: float | None = 2,
    now: datetime | None = None,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> list[MatchFixture]:
    """Scrape fixtures from live.500.com; default = kickoff within 2 days, 世界杯 only."""
    sess = session or _session()
    now = to_beijing(now or now_beijing())
    league_filter = set(leagues) if leagues is not None else None
    resp = sess.get("https://live.500.com/", timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    html = _decode(resp.content)
    soup = BeautifulSoup(html, "html.parser")

    seen: set[str] = set()
    fixtures: list[MatchFixture] = []
    for a in soup.find_all("a", href=re.compile(r"youliao-\d+\.shtml")):
        m = re.search(r"youliao-(\d+)\.shtml", a.get("href", ""))
        if not m:
            continue
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)

        tr = a.find_parent("tr")
        row_text = tr.get_text("|", strip=True) if tr else ""
        league = _parse_league_from_tr(tr)
        if league_filter is not None and league not in league_filter:
            continue
        kickoff = _parse_kickoff(row_text, ref=now)
        home, away = _parse_teams_from_row(row_text)
        order_id = ""
        match_num = ""
        if tr is not None:
            order_id = str(tr.get("order") or "")
            inp = tr.find("input", attrs={"value": fid})
            if inp and inp.parent:
                txt = inp.parent.get_text(strip=True)
                if txt and re.match(r"周[一二三四五六日天]\d+", txt):
                    match_num = txt

        if within_days is not None and not _within_days(kickoff, days=within_days, now=now):
            continue

        status = _parse_row_status(tr)
        fixtures.append(MatchFixture(
            fixture_id=fid,
            home=home,
            away=away,
            kickoff=kickoff,
            order_id=order_id,
            match_num=match_num,
            league=league,
            status_phase=status.get("phase") or "",
            live_score=status.get("score") or "",
            status_label=status.get("label") or "",
        ))

    fixtures.sort(key=lambda f: f.kickoff or datetime.max)
    return fixtures


@dataclass
class DownloadResult:
    fixture_id: str
    match_name: str
    asian: Path | None = None
    european: Path | None = None


def download_match_pair(
    fixture_id: str,
    output_dir: str | Path,
    *,
    ah_only: bool = False,
    eu_only: bool = False,
    delay_sec: float = 0.5,
) -> DownloadResult:
    """Download AH + EU xls for one fixture into output_dir."""
    out = Path(output_dir)
    sess = _session()
    info = fetch_match_info(sess, fixture_id)
    result = DownloadResult(fixture_id=info.fixture_id, match_name=info.base_name)

    if not eu_only:
        result.asian = download_asian_handicap_xls(sess, info.fixture_id, out / info.ah_filename)
        time.sleep(delay_sec)

    if not ah_only:
        result.european = download_european_odds_xls(
            sess, info.fixture_id, out / info.eu_filename,
        )
    return result


def _print_fixtures(fixtures: Iterable[MatchFixture], *, within_days: float | None) -> None:
    window = f"（{within_days} 天内）" if within_days is not None else "（全部）"
    print(f"{'开球':<12} {'FID':<10} {'对阵'} {window}")
    print("-" * 52)
    for fx in fixtures:
        name = fx.base_name if fx.home else fx.fixture_id
        print(f"{fx.kickoff_label:<12} {fx.fixture_id:<10} {name}")


def download_upcoming(
    output_dir: str | Path,
    *,
    within_days: float | None = 2,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
    ah_only: bool = False,
    eu_only: bool = False,
    delay_sec: float = 0.8,
) -> list[DownloadResult]:
    """Download all fixtures within N days from live.500.com."""
    fixtures = fetch_live_fixtures(within_days=within_days, leagues=leagues)
    if not fixtures:
        return []
    results: list[DownloadResult] = []
    for i, fx in enumerate(fixtures):
        if i:
            time.sleep(delay_sec)
        try:
            results.append(download_match_pair(
                fx.fixture_id, output_dir,
                ah_only=ah_only, eu_only=eu_only,
                delay_sec=delay_sec,
            ))
        except (Download500Error, requests.RequestException) as exc:
            print(f"跳过 {fx.base_name} ({fx.fixture_id}): {exc}", file=sys.stderr)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 500.com 下载实时亚盘/欧赔 Excel（与网站「下载」按钮同源）",
    )
    parser.add_argument(
        "--fid", "--id",
        dest="fixture_id",
        help="比赛 ID 或分析页 URL，如 1359227 或 https://odds.500.com/fenxi/youliao-1359227.shtml",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出 live.500.com 赛程（默认仅 2 天内）",
    )
    parser.add_argument(
        "--upcoming",
        action="store_true",
        help="批量下载 2 天内所有比赛的亚盘+欧赔",
    )
    parser.add_argument(
        "--all-leagues",
        action="store_true",
        help="包含全部联赛（默认仅世界杯）",
    )
    parser.add_argument(
        "--days", type=float, default=2,
        help="时间窗口：仅包含开球时间在「现在 ~ N 天」内的比赛（默认 2）",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="不按时间过滤，列出/下载全部赛程（不推荐）",
    )
    parser.add_argument(
        "-o", "--output", default="downloads",
        help="保存目录，默认 ./downloads",
    )
    parser.add_argument("--ah-only", action="store_true", help="只下载亚盘")
    parser.add_argument("--eu-only", action="store_true", help="只下载欧赔")
    parser.add_argument(
        "--then-predict",
        action="store_true",
        help="下载完成后调用 predict.py 输出规则推荐（不调 AI）",
    )
    args = parser.parse_args(argv)
    within = None if args.all else args.days
    leagues = None if args.all_leagues else DEFAULT_LEAGUES

    if args.list:
        fixtures = fetch_live_fixtures(within_days=within, leagues=leagues)
        if not fixtures:
            print("未找到符合条件的比赛", file=sys.stderr)
            return 1
        _print_fixtures(fixtures, within_days=within)
        print(f"\n共 {len(fixtures)} 场")
        return 0

    if args.upcoming:
        results = download_upcoming(
            args.output,
            within_days=within,
            leagues=leagues,
            ah_only=args.ah_only,
            eu_only=args.eu_only,
        )
        if not results:
            print("未找到可下载的比赛", file=sys.stderr)
            return 1
        print(f"\n已下载 {len(results)} 场 → {args.output}")
        for r in results:
            print(f"  {r.match_name} ({r.fixture_id})")
        if args.then_predict:
            print("\n提示: 批量预测请用 predict_sheet.py 或 predict_ai.py", file=sys.stderr)
        return 0

    if not args.fixture_id:
        parser.error("请指定 --fid、--list 或 --upcoming")

    try:
        paths = download_match_pair(
            args.fixture_id,
            args.output,
            ah_only=args.ah_only,
            eu_only=args.eu_only,
        )
    except (Download500Error, requests.RequestException) as exc:
        print(f"下载失败: {exc}", file=sys.stderr)
        return 1

    print(f"比赛: {paths.match_name} (fid={paths.fixture_id})")
    if paths.asian:
        print(f"  亚盘 → {paths.asian}")
    if paths.european:
        print(f"  欧赔 → {paths.european}")

    if args.then_predict and paths.asian and paths.european:
        from predict import build_payload, print_recommendation
        from history import load_all_history
        from recommend import build_recommendation

        print("\n--- 规则引擎快速预览 ---")
        payload = build_payload(
            str(paths.asian), str(paths.european),
            history=load_all_history(),
        )
        print_recommendation(build_recommendation(payload))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
