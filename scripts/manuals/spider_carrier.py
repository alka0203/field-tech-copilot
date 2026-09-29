"""URL-seeded spider for Carrier's shareddocs.com portal.

Directory listing (e.g. https://www.shareddocs.com/hvac/docs/1009/Public/04/)
returns HTTP 403 site-wide, so the old approach of enumerating a listing page
and harvesting href links no longer works.  However, individual PDF files are
publicly accessible by direct URL.  This script hard-codes a set of confirmed
working seed URLs (verified 2026-09-29, all returned HTTP 200) and fetches each
one directly.

Docs are "Copyright Carrier Corp." with no redistribution grant: this script
only ever writes the manifest (url + sha256), the raw PDF stays in the
gitignored data/raw/ cache for local extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "carrier"

# Maps model_family -> list of direct PDF URLs.
# All URLs confirmed to return HTTP 200 as of 2026-09-29.
# Directory listing is 403 site-wide; files are publicly accessible by direct URL.
SEED_URLS: dict[str, list[str]] = {
    "40MAQ": [
        "https://www.shareddocs.com/hvac/docs/1009/Public/00/40MAQ-01SM.pdf",
    ],
    "38MAQB": [
        "https://www.shareddocs.com/hvac/docs/1009/Public/08/38MAQ-01SM.pdf",
    ],
    "25HCE": [
        "https://www.shareddocs.com/hvac/docs/1009/Public/0D/25HBC-HCE-03SI.pdf",
        "https://www.shareddocs.com/hvac/docs/1009/Public/03/24-25-9SM.pdf",
    ],
}


def main() -> None:
    records = []
    failures: list[str] = []

    with httpx.Client() as client:
        for model_family, pdf_urls in SEED_URLS.items():
            for pdf_url in pdf_urls:
                if not robots_allow(pdf_url):
                    print(f"[skip] robots.txt disallows {pdf_url}", file=sys.stderr)
                    continue
                try:
                    record = fetch_pdf_head_and_hash(client, pdf_url, BRAND, model_family, pdf_url)
                    records.append(record)
                    print(f"[ok] {pdf_url} -> {record.sha256[:12]} ({record.bytes} bytes)")
                except httpx.HTTPError as e:
                    msg = f"{pdf_url}: {e}"
                    print(f"[fail] {msg}", file=sys.stderr)
                    failures.append(msg)
                polite_sleep()

    append_manifest(records)
    print(f"Wrote {len(records)} records to manuals_manifest.csv")

    if failures:
        print("\nFailed URLs:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
