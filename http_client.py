"""HTTP session with polite scraping defaults and failure backoff."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

BLOCK_KEYWORDS = ("验证码", "访问过于频繁", "captcha", "Forbidden", "安全验证")


@dataclass
class ScraperGuard:
    consecutive_failures: int = 0
    backoff_until: float = 0.0
    min_delay: float = 1.2
    max_delay: float = 3.0
    blocked_sources: set[str] = field(default_factory=set)

    def wait_turn(self) -> None:
        now = time.time()
        if now < self.backoff_until:
            sleep_for = self.backoff_until - now
            log.warning("反爬退避中，等待 %.1fs", sleep_for)
            time.sleep(sleep_for)
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def record_success(self, source: str) -> None:
        self.consecutive_failures = 0
        self.blocked_sources.discard(source)

    def record_failure(self, source: str, *, status: int | None = None, snippet: str = "") -> None:
        self.consecutive_failures += 1
        blocked = status in (403, 429) or any(k.lower() in snippet.lower() for k in BLOCK_KEYWORDS)
        if blocked:
            self.blocked_sources.add(source)
        # exponential backoff up to 15 min
        delay = min(900, 30 * (2 ** min(self.consecutive_failures - 1, 5)))
        self.backoff_until = time.time() + delay
        log.warning(
            "请求失败 source=%s status=%s failures=%d backoff=%ds",
            source, status, self.consecutive_failures, delay,
        )

    def is_blocked(self, source: str) -> bool:
        return source in self.blocked_sources


def make_session(*, referer: str = "https://live.500.com/") -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Connection": "keep-alive",
    })
    return s


def get_text(
    session: requests.Session,
    url: str,
    *,
    source: str,
    guard: ScraperGuard,
    timeout: float = 30,
) -> str:
    if guard.is_blocked(source):
        raise RuntimeError(f"数据源 {source} 处于退避/封禁状态")
    guard.wait_turn()
    resp = session.get(url, timeout=timeout)
    text = _decode(resp.content)
    if resp.status_code != 200 or _looks_blocked(text):
        guard.record_failure(source, status=resp.status_code, snippet=text[:300])
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    guard.record_success(source)
    return text


def _decode(content: bytes) -> str:
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("gb18030", errors="replace")


def _looks_blocked(text: str) -> bool:
    sample = text[:2000]
    return any(k in sample for k in BLOCK_KEYWORDS)
