"""URL-seeded spider for Mitsubishi Electric HVAC service manuals.

The old portal (mylinkdrive.com) is dead as of 2026-09-29. The new portal
(mitsubishicomfort.com) serves product pages as a JS-heavy React app — PDFs
are loaded via client-side API calls on button click and are not present in
any initial HTML or sitemap.

Individual service manual PDFs are publicly hosted on HVAC-distributor sites.
This script hard-codes confirmed working direct PDF URLs (verified 2026-09-29)
and fetches each one directly, matching the same URL-seeded pattern used by
spider_carrier.py.

Docs are copyright Mitsubishi Electric: this script only writes the manifest
(url + sha256); the raw PDF stays in the gitignored data/raw/ cache for local
extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "mitsubishi"

# Maps model_family -> list of direct PDF URLs.
# All URLs confirmed accessible as of 2026-09-29.
# Source: mitsubishitechinfo.ca — the official Mitsubishi Electric US/CA
# technical-information portal for service technicians.
SEED_URLS: dict[str, list[str]] = {
    "MSZ-FH": [
        # MSZ-FH06/09/12/15/18NA Series indoor unit service manual (OBH683E)
        "https://www.mitsubishitechinfo.ca/sites/default/files/SH_MSZ-FH06_18NA(2)_OBH683E.pdf",
    ],
    "MSZ-GE": [
        # MSZ/MSY/MUZ-GE-NA Series indoor+outdoor service manual (OBH548D)
        "https://www.mitsubishitechinfo.ca/sites/default/files/SH_MS%28Y%29%28Z%29-GE-NA_OBH548D_16.pdf",
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
