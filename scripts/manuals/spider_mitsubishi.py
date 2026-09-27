"""Static spider for Mitsubishi Electric's MyLinkDrive portal.

MyLinkDrive is folder-style direct-PDF hosting, but newer R-454B docs are
migrating to a "HVAC Pro" portal that may require sign-in. Per sources.yaml,
this spider must fail loudly (raise / print clearly) rather than silently
returning zero results when the portal shape changes, so a cron run doesn't
quietly go stale.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "mitsubishi"
LISTING_URLS = {
    "MSZ": "https://meus1.mylinkdrive.com/",
    "MXZ": "https://nonul.mylinkdrive.com/",
}

LOGIN_MARKERS = ("sign in", "log in", "hvac pro", "password")


class PortalShapeChanged(RuntimeError):
    """Raised when a listing page looks like a login wall instead of a folder listing."""


def find_pdf_links(client: httpx.Client, listing_url: str) -> list[str]:
    if not robots_allow(listing_url):
        raise PortalShapeChanged(f"robots.txt now disallows {listing_url}")
    resp = client.get(listing_url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    lowered = resp.text.lower()
    if any(marker in lowered for marker in LOGIN_MARKERS):
        raise PortalShapeChanged(
            f"{listing_url} looks like a login wall now (matched a login marker) — "
            "check whether this model family moved to the HVAC Pro portal."
        )
    soup = BeautifulSoup(resp.text, "html.parser")
    links = [
        httpx.URL(listing_url).join(a["href"]).human_repr()
        for a in soup.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
    ]
    if not links:
        raise PortalShapeChanged(f"{listing_url} returned zero PDF links — page structure may have changed.")
    return links


def main() -> None:
    records = []
    failures = []
    with httpx.Client() as client:
        for model_family, listing_url in LISTING_URLS.items():
            try:
                pdf_urls = find_pdf_links(client, listing_url)
            except (httpx.HTTPError, PortalShapeChanged) as e:
                failures.append((model_family, listing_url, str(e)))
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
                    failures.append((model_family, pdf_url, str(e)))
                polite_sleep()
    append_manifest(records)
    print(f"Wrote {len(records)} records to manuals_manifest.csv")

    if failures:
        print("\n=== FAILURES (portal may have changed shape — investigate, don't ignore) ===", file=sys.stderr)
        for model_family, url, reason in failures:
            print(f"  [{model_family}] {url}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
