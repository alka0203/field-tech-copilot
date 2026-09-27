"""Static spider for Carrier's shareddocs.com portal.

shareddocs.com serves direct PDF links from plain HTML listing pages, so a
BeautifulSoup + httpx spider is more reliable here than a JS crawler.
Docs are "Copyright Carrier Corp." with no redistribution grant: this script
only ever writes the manifest (url + sha256), the raw PDF stays in the
gitignored data/raw/ cache for local extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "carrier"
LISTING_URLS = {
    "40MAQ": "https://www.shareddocs.com/hvac/docs/1009/Public/04/",
}


def find_pdf_links(client: httpx.Client, listing_url: str) -> list[str]:
    if not robots_allow(listing_url):
        print(f"[skip] robots.txt disallows {listing_url}", file=sys.stderr)
        return []
    resp = client.get(listing_url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return [
        httpx.URL(listing_url).join(a["href"]).human_repr()
        for a in soup.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
    ]


def main() -> None:
    records = []
    with httpx.Client() as client:
        for model_family, listing_url in LISTING_URLS.items():
            try:
                pdf_urls = find_pdf_links(client, listing_url)
            except httpx.HTTPError as e:
                print(f"[fail] could not list {listing_url}: {e}", file=sys.stderr)
                continue
            for pdf_url in pdf_urls:
                if not robots_allow(pdf_url):
                    print(f"[skip] robots.txt disallows {pdf_url}", file=sys.stderr)
                    continue
                try:
                    record = fetch_pdf_head_and_hash(client, pdf_url, BRAND, model_family, listing_url)
                    records.append(record)
                    print(f"[ok] {pdf_url} -> {record.sha256[:12]} ({record.bytes} bytes)")
                except httpx.HTTPError as e:
                    print(f"[fail] {pdf_url}: {e}", file=sys.stderr)
                polite_sleep()
    append_manifest(records)
    print(f"Wrote {len(records)} records to manuals_manifest.csv")


if __name__ == "__main__":
    main()
