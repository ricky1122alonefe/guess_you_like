#!/usr/bin/env python3
"""Fetch referee match history from FootyMetrics.

Example:
    python scripts/fetch_referee_history.py \
        --url "https://www.footymetrics.com/referees/33287-adham-mohammad-tumah-makhadmeh"

Output:
    data/referees/33287-adham-mohammad-tumah-makhadmeh.csv
    data/referees/33287-adham-mohammad-tumah-makhadmeh.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_referee_history")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_match_cell(text: str) -> dict[str, str | int]:
    """Parse 'NZL1-5BEL' into home_team, away_team, home_score, away_score."""
    # Some cells may have spaces or line breaks; normalize first.
    cleaned = re.sub(r"\s+", "", text)
    # Pattern: team1 score1-score2 team2 (teams are 3-letter abbreviations in most cases)
    m = re.match(r"^([A-Za-z].*?)(\d+)-(\d+)([A-Za-z].*)$", cleaned)
    if not m:
        return {"match_raw": text, "home_team": "", "away_team": "", "home_score": "", "away_score": ""}
    return {
        "match_raw": text,
        "home_team": m.group(1).strip(),
        "home_score": int(m.group(2)),
        "away_score": int(m.group(3)),
        "away_team": m.group(4).strip(),
    }


def _extract_id_from_url(url: str) -> str:
    path = url.rstrip("/").split("/")[-1]
    # e.g. "33287-adham-mohammad-tumah-makhadmeh"
    return path


def fetch_referee_history(url: str, *, delay: float = 1.5) -> dict:
    """Download and parse a FootyMetrics referee page."""
    log.info("Fetching %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(delay)

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise RuntimeError("No tables found on page")

    # Table 0 is the recent matches table.
    recent_table = tables[0]
    rows = recent_table.find_all("tr")
    if len(rows) < 2:
        raise RuntimeError("Recent matches table is empty")

    records: list[dict] = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        match_parsed = _parse_match_cell(cells[1].get_text(strip=True))
        records.append(
            {
                "date": cells[0].get_text(strip=True),
                **match_parsed,
                "yellow_cards": int(cells[2].get_text(strip=True) or 0),
                "red_cards": int(cells[3].get_text(strip=True) or 0),
                "fouls": int(cells[4].get_text(strip=True) or 0),
                "penalties": int(cells[5].get_text(strip=True) or 0),
            }
        )

    # Try to find aggregate summary from the last table with competition rows.
    summary: dict[str, Any] = {"matches": len(records)}
    for table in reversed(tables):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if headers and "League" in headers[0]:
            comp_rows = []
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 6:
                    continue
                comp_rows.append(
                    {
                        "league": cells[0].get_text(strip=True),
                        "matches": cells[1].get_text(strip=True),
                        "yellow_cards": cells[2].get_text(strip=True),
                        "red_cards": cells[3].get_text(strip=True),
                        "fouls": cells[4].get_text(strip=True),
                        "penalties": cells[5].get_text(strip=True),
                    }
                )
            summary["by_competition"] = comp_rows
            break

    return {
        "source_url": url,
        "referee_id": _extract_id_from_url(url),
        "summary": summary,
        "records": records,
    }


def save(data: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rid = data["referee_id"]
    json_path = output_dir / f"{rid}.json"
    csv_path = output_dir / f"{rid}.csv"

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    import csv

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
                "yellow_cards",
                "red_cards",
                "fouls",
                "penalties",
            ],
        )
        writer.writeheader()
        for rec in data["records"]:
            writer.writerow({k: rec[k] for k in writer.fieldnames})

    return json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch referee match history from FootyMetrics")
    parser.add_argument("--url", required=True, help="FootyMetrics referee page URL")
    parser.add_argument(
        "--output-dir",
        default="data/referees",
        help="Output directory for CSV and JSON (default: data/referees)",
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Polite delay between requests (seconds)")
    args = parser.parse_args(argv)

    data = fetch_referee_history(args.url, delay=args.delay)
    json_path, csv_path = save(data, Path(args.output_dir))
    log.info("Saved %d records to %s and %s", len(data["records"]), csv_path, json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
