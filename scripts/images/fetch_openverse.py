"""Free, license-clean image search via the Openverse API.

No API key needed at this volume: anonymous requests are throttled to
1 req/sec and page_size must stay <= 20 (per Openverse's own docs), which
this script respects.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import ImageRecord, append_manifest, load_queries

API = "https://api.openverse.org/v1/images/"
PAGE_SIZE = 20
RATE_LIMIT_SECONDS = 1.1


def search(client: httpx.Client, query: str, page_size: int = PAGE_SIZE) -> list[dict]:
    resp = client.get(API, params={"q": query, "page_size": page_size}, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("results", [])


def main(limit_queries: int | None = None) -> None:
    sources_yaml = Path(__file__).resolve().parents[2] / "sources.yaml"
    queries = load_queries(sources_yaml)
    if limit_queries:
        queries = queries[:limit_queries]

    records = []
    with httpx.Client(headers={"User-Agent": "field-tech-copilot-research/0.1"}) as client:
        for brand, family, query in queries:
            try:
                results = search(client, query)
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
                        provider="openverse",
                        image_url=r.get("url", ""),
                        source_page=r.get("foreign_landing_url", ""),
                        license=r.get("license", ""),
                        license_url=r.get("license_url", ""),
                        attribution=r.get("attribution", ""),
                        width=r.get("width") or 0,
                        height=r.get("height") or 0,
                    )
                )
            print(f"[ok] {query!r}: {len(results)} results")
            time.sleep(RATE_LIMIT_SECONDS)

    append_manifest(records)
    print(f"Wrote {len(records)} records to images_manifest.csv")


if __name__ == "__main__":
    main()
