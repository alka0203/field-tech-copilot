"""Shared helpers for manual spiders: polite fetching, hashing, manifest rows."""
from __future__ import annotations

import csv
import hashlib
import time
import urllib.robotparser
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "field-tech-copilot-research-bot/0.1 (contact: alka.sv54@gmail.com; manifest-only, no redistribution)"
REQUEST_DELAY_SECONDS = 1.0  # polite crawl rate on manufacturer sites
MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "manuals_manifest.csv"
MANIFEST_FIELDS = [
    "brand", "model_family", "url", "sha256", "bytes", "content_type",
    "retrieved_at", "source_page", "http_status", "notes",
]


@dataclass
class ManualRecord:
    brand: str
    model_family: str
    url: str
    sha256: str
    bytes: int
    content_type: str
    retrieved_at: str
    source_page: str
    http_status: int
    notes: str = ""


def append_manifest(records: list[ManualRecord]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not MANIFEST_PATH.exists()
    with MANIFEST_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))


def fetch_pdf_head_and_hash(
    client: httpx.Client, url: str, brand: str, model_family: str, source_page: str
) -> ManualRecord:
    """HEAD-check then GET a candidate PDF, hashing bytes without keeping them
    around longer than needed for the local raw cache (gitignored)."""
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30.0)
    content = resp.content
    digest = hashlib.sha256(content).hexdigest()
    raw_dir = Path(__file__).resolve().parents[2] / "data" / "raw" / "manuals" / brand
    raw_dir.mkdir(parents=True, exist_ok=True)
    if resp.status_code == 200 and resp.headers.get("content-type", "").lower().startswith("application/pdf"):
        (raw_dir / f"{digest[:16]}.pdf").write_bytes(content)
    return ManualRecord(
        brand=brand,
        model_family=model_family,
        url=url,
        sha256=digest,
        bytes=len(content),
        content_type=resp.headers.get("content-type", ""),
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_page=source_page,
        http_status=resp.status_code,
    )


def polite_sleep() -> None:
    time.sleep(REQUEST_DELAY_SECONDS)


_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_allow(url: str) -> bool:
    """Check robots.txt for the URL's origin, caching parsers per host.
    Fails closed: an unreachable robots.txt is treated as disallow."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            return False
        _robots_cache[origin] = rp
    return rp.can_fetch(USER_AGENT, url)
