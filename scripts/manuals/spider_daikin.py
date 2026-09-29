"""URL-seeded spider for Daikin HVAC service manuals.

The resource center (daikincomfort.com/resource-center) is JS-driven and
anti-bot hardened — product pages return near-empty responses to crawlers.
Individual service manual PDFs are publicly accessible by direct URL on both
daikincomfort.com and backend.daikincomfort.com.  This script hard-codes a
set of confirmed working seed URLs (verified 2026-09-29) and fetches each
one directly, matching the same pattern used by spider_carrier.py.

Docs are copyright Daikin: this script only writes the manifest (url + sha256);
the raw PDF stays in the gitignored data/raw/ cache for local extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import USER_AGENT, append_manifest, fetch_pdf_head_and_hash, polite_sleep, robots_allow

BRAND = "daikin"

# Maps model_family -> list of direct PDF URLs.
# All URLs confirmed to return HTTP 200 as of 2026-09-29.
# Source: daikincomfort.com and backend.daikincomfort.com document library.
SEED_URLS: dict[str, list[str]] = {
    "FTXS": [
        # Inverter Pair FTXS-L / FDXS-L Series — SiUS091133
        "https://daikincomfort.com/docs/default-source/lv-series-slim-duct/sm-fd(t)xs09-36lvju-rk(x)s09-36lvju.pdf",
        # Inverter Pair H-Series / FTXS-HV — SiUS04-924_A
        "https://daikincomfort.com/docs/default-source/skyair-system---heat-pump/sius04-924_a-rxs-ftxs_hvju-service-manual.pdf",
    ],
    "FTKX": [
        # Inverter Single Split Wall Mount FTK(X)B Series — SM-5WM-Y-NA-B1
        "https://daikincomfort.com/docs/default-source/17-series-wall-mount/sm-ftk(x)b_axvju-rk(x)b_axvju2.pdf",
    ],
    "CTX": [
        # Inverter Multi-Split CTX Series 2-zone — DAMA-SM-21-003
        "https://daikincomfort.com/docs/default-source/daikin-cirra-2-zone-multi-zone/sm-ctx-axvju_2mx18axvju-(dama-sm-21-003).pdf",
    ],
    "RMXS": [
        # Multi-Split RMXS-L Series 8-zone — SiUS181631EA
        "https://daikincomfort.com/docs/default-source/rmxs-series-8-zone-multi-split/sm-sius181631e---rmxs-service-manual.pdf",
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
