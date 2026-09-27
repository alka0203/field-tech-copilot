"""Paid image search via the Brave Search API (Images endpoint).

$5 per 1,000 requests, $5 free credit/month per Brave's pricing page. Costs
real money once the free credit is used, so this script:
  - never runs unless BRAVE_API_KEY is set in the environment
  - takes an explicit --max-queries cap (default 50) so a typo can't burn budget
  - only writes url + metadata to the manifest, never downloads/stores images
    directly (Brave grants no redistribution rights over the results)

Usage:
  export BRAVE_API_KEY=...
  python scripts/images/fetch_brave.py --max-queries 50
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import ImageRecord, append_manifest, load_queries

API = "https://api.search.brave.com/res/v1/images/search"
RATE_LIMIT_SECONDS = 1.1


def search(client: httpx.Client, api_key: str, query: str, count: int = 20) -> list[dict]:
    resp = client.get(
        API,
        params={"q": query, "count": count},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-queries", type=int, default=50, help="Hard cap on paid queries this run.")
    args = parser.parse_args()

    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        print(
            "BRAVE_API_KEY is not set — refusing to run a paid search. "
            "Set it in your shell (never commit it) and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    sources_yaml = Path(__file__).resolve().parents[2] / "sources.yaml"
    queries = load_queries(sources_yaml)
    # Prioritize the query types most likely to need a paid, higher-relevance
    # index: nameplates and error displays are the long-tail images that
    # Openverse/Commons rarely have.
    queries = [q for q in queries if "nameplate" in q[2] or "error" in q[2] or "fault" in q[2]]
    queries = queries[: args.max_queries]
    print(f"Running {len(queries)} paid Brave queries (capped by --max-queries={args.max_queries}).")

    records = []
    with httpx.Client() as client:
        for brand, family, query in queries:
            try:
                results = search(client, api_key, query)
            except httpx.HTTPError as e:
                print(f"[fail] {query!r}: {e}", file=sys.stderr)
                time.sleep(RATE_LIMIT_SECONDS)
                continue
            for r in results:
                props = r.get("properties", {})
                records.append(
                    ImageRecord(
                        brand=brand,
                        model_family=family,
                        query=query,
                        provider="brave",
                        image_url=props.get("url", ""),
                        source_page=r.get("url", ""),
                        width=props.get("width") or 0,
                        height=props.get("height") or 0,
                    )
                )
            print(f"[ok] {query!r}: {len(results)} results")
            time.sleep(RATE_LIMIT_SECONDS)

    append_manifest(records)
    print(f"Wrote {len(records)} records to images_manifest.csv (no license grant — do not redistribute the images)")


if __name__ == "__main__":
    main()
