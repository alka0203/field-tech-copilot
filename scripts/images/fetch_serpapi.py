"""Paid image search via SerpApi's Google Images engine.

Free plan: 250 searches/month. Same cost-safety pattern as fetch_brave.py:
requires SERPAPI_API_KEY, hard-capped by --max-queries, manifest-only (no
image bytes stored — SerpApi results carry no redistribution rights).

Usage:
  export SERPAPI_API_KEY=...
  python scripts/images/fetch_serpapi.py --max-queries 50
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

API = "https://serpapi.com/search"
RATE_LIMIT_SECONDS = 1.1


def search(client: httpx.Client, api_key: str, query: str) -> list[dict]:
    resp = client.get(
        API,
        params={"engine": "google_images", "q": query, "api_key": api_key},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("images_results", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-queries", type=int, default=50, help="Hard cap on paid queries this run.")
    args = parser.parse_args()

    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        print(
            "SERPAPI_API_KEY is not set — refusing to run a paid search. "
            "Set it in your shell (never commit it) and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    sources_yaml = Path(__file__).resolve().parents[2] / "sources.yaml"
    queries = load_queries(sources_yaml)
    queries = [q for q in queries if "nameplate" in q[2] or "error" in q[2] or "fault" in q[2]]
    queries = queries[: args.max_queries]
    print(f"Running {len(queries)} paid SerpApi queries (capped by --max-queries={args.max_queries}).")

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
                records.append(
                    ImageRecord(
                        brand=brand,
                        model_family=family,
                        query=query,
                        provider="serpapi",
                        image_url=r.get("original", ""),
                        source_page=r.get("link", ""),
                        width=r.get("original_width") or 0,
                        height=r.get("original_height") or 0,
                    )
                )
            print(f"[ok] {query!r}: {len(results)} results")
            time.sleep(RATE_LIMIT_SECONDS)

    append_manifest(records)
    print(f"Wrote {len(records)} records to images_manifest.csv (no license grant — do not redistribute the images)")


if __name__ == "__main__":
    main()
