"""Spider for Mitsubishi Electric HVAC product manuals via mitsubishicomfort.com.

NOTE: The old portal (mylinkdrive.com subdomains — meus1.mylinkdrive.com and
nonul.mylinkdrive.com) is dead as of 2026-09-29. Both subdomains are either
DNS-gone or connection-refused and cannot be relied upon for any future crawl.

New approach:
  1. Fetch https://www.mitsubishicomfort.com/products/sitemap.xml with httpx.
  2. Filter <loc> entries to product-page URLs that belong to target families
     (MSZ, MUZ, MXZ, PUZ, M-Series, P-Series).
  3. For each matching product page, use crawl4ai AsyncWebCrawler (Playwright)
     to render the JavaScript-heavy page and scrape .pdf hrefs via regex.
  4. For each PDF URL: robots_allow check, fetch_pdf_head_and_hash, polite_sleep.
  5. Write all collected records to manuals_manifest.csv via append_manifest.

Fails loudly (sys.exit(1)) if:
  - The sitemap yields zero matching product pages.
  - Zero PDFs are found across all product pages.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "mitsubishi"
SITEMAP_URL = "https://www.mitsubishicomfort.com/products/sitemap.xml"

# URL slug fragments that identify target product families (case-insensitive).
FAMILY_PATTERNS: list[str] = ["msz", "muz", "mxz", "puz", "m-series", "p-series"]


def _model_family_from_url(url: str) -> str:
    """Derive a canonical model-family label from a product-page URL slug."""
    low = url.lower()
    if "msz" in low:
        return "MSZ"
    if "muz" in low:
        return "MUZ"
    if "mxz" in low:
        return "MXZ"
    if "puz" in low or "p-series" in low:
        return "PUZ"
    # m-series is the catch-all residential multi-zone brand label
    return "M-SERIES"


def _fetch_sitemap_product_urls(client: httpx.Client) -> list[str]:
    """Fetch the products sitemap and return URLs matching the target families."""
    resp = client.get(SITEMAP_URL, headers={"User-Agent": USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    # Parse <loc> tags with a simple regex — avoids namespace headaches with lxml.
    all_locs: list[str] = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", resp.text)
    matched = [
        loc for loc in all_locs
        if any(pat in loc.lower() for pat in FAMILY_PATTERNS)
    ]
    return matched


async def _extract_pdf_urls_from_page(page_url: str) -> list[str]:
    """Render *page_url* with crawl4ai Playwright and return all .pdf hrefs found."""
    # Import here so the module remains importable even if crawl4ai is not yet
    # installed in a minimal test environment.
    from crawl4ai import AsyncWebCrawler  # type: ignore[import]

    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(
            url=page_url,
            headers={"User-Agent": USER_AGENT},
        )
        html: str = result.html or ""

    # Match both absolute and site-relative PDF hrefs.
    raw_hrefs: list[str] = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.IGNORECASE)
    resolved: list[str] = []
    for href in raw_hrefs:
        if href.lower().startswith("http"):
            resolved.append(href)
        else:
            resolved.append(urljoin(page_url, href))
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for u in resolved:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def main() -> None:
    records = []
    pdf_failures: list[tuple[str, str, str]] = []

    with httpx.Client() as client:
        # Step 1 — sitemap
        print(f"Fetching sitemap: {SITEMAP_URL}")
        try:
            product_urls = _fetch_sitemap_product_urls(client)
        except httpx.HTTPError as exc:
            print(f"[fail] Could not fetch sitemap: {exc}", file=sys.stderr)
            sys.exit(1)

        if not product_urls:
            print(
                "[fail] Sitemap yielded zero matching product pages. "
                "Check FAMILY_PATTERNS or whether the sitemap URL has changed.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Found {len(product_urls)} matching product page(s).")

        # Step 2 — crawl each product page for PDF links
        for page_url in product_urls:
            model_family = _model_family_from_url(page_url)
            print(f"  Crawling [{model_family}] {page_url}")

            try:
                pdf_urls = asyncio.run(_extract_pdf_urls_from_page(page_url))
            except Exception as exc:  # crawl4ai / Playwright errors
                print(f"  [fail] JS render failed for {page_url}: {exc}", file=sys.stderr)
                pdf_failures.append((model_family, page_url, str(exc)))
                continue

            if not pdf_urls:
                print(f"  [skip] No PDFs found on {page_url}")
                continue

            # Step 3 — fetch each PDF
            for pdf_url in pdf_urls:
                if not robots_allow(pdf_url):
                    print(f"  [skip] robots.txt disallows {pdf_url}", file=sys.stderr)
                    continue
                try:
                    record = fetch_pdf_head_and_hash(client, pdf_url, BRAND, model_family, page_url)
                    records.append(record)
                    print(f"  [ok] {pdf_url} -> {record.sha256[:12]} ({record.bytes} bytes)")
                except httpx.HTTPError as exc:
                    print(f"  [fail] {pdf_url}: {exc}", file=sys.stderr)
                    pdf_failures.append((model_family, pdf_url, str(exc)))
                polite_sleep()

    # Step 4 — write manifest
    if not records:
        print(
            "[fail] Zero PDFs collected across all product pages. "
            "The site structure may have changed — investigate before re-running.",
            file=sys.stderr,
        )
        sys.exit(1)

    append_manifest(records)
    print(f"\nWrote {len(records)} record(s) to manuals_manifest.csv")

    if pdf_failures:
        print("\n=== FAILURES ===", file=sys.stderr)
        for model_family, url, reason in pdf_failures:
            print(f"  [{model_family}] {url}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
