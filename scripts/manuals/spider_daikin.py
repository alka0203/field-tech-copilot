"""JS-rendered crawl for Daikin's resource center using Crawl4AI.

Daikin's docs are linked from a JS-driven resource center rather than a plain
HTML listing, so this uses Crawl4AI (Playwright-backed) to render the page,
then extracts direct PDF links from the rendered DOM and hands them to the
same httpx-based download + hash + manifest path the static spiders use.

Requires: pip install crawl4ai && crawl4ai-setup (installs Playwright browsers).
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "daikin"
SEED_URLS = {
    "FTXS": "https://www.daikinac.com/resource-center/",
}
PDF_LINK_RE = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.IGNORECASE)


async def render_and_extract_pdf_links(url: str) -> list[str]:
    from crawl4ai import AsyncWebCrawler

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, user_agent=USER_AGENT)
        html = result.html or ""
    return [httpx.URL(url).join(m).human_repr() for m in PDF_LINK_RE.findall(html)]


def main() -> None:
    records = []
    with httpx.Client() as client:
        for model_family, seed_url in SEED_URLS.items():
            if not robots_allow(seed_url):
                print(f"[skip] robots.txt disallows {seed_url}", file=sys.stderr)
                continue
            try:
                pdf_urls = asyncio.run(render_and_extract_pdf_links(seed_url))
            except Exception as e:
                print(f"[fail] could not render {seed_url}: {e}", file=sys.stderr)
                continue
            if not pdf_urls:
                print(f"[warn] {seed_url} rendered but yielded zero PDF links — check page structure", file=sys.stderr)
            for pdf_url in pdf_urls:
                if not robots_allow(pdf_url):
                    print(f"[skip] robots.txt disallows {pdf_url}", file=sys.stderr)
                    continue
                try:
                    record = fetch_pdf_head_and_hash(client, pdf_url, BRAND, model_family, seed_url)
                    records.append(record)
                    print(f"[ok] {pdf_url} -> {record.sha256[:12]} ({record.bytes} bytes)")
                except httpx.HTTPError as e:
                    print(f"[fail] {pdf_url}: {e}", file=sys.stderr)
                polite_sleep()
    append_manifest(records)
    print(f"Wrote {len(records)} records to manuals_manifest.csv")


if __name__ == "__main__":
    main()
