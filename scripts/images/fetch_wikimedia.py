"""Free image search via the Wikimedia Commons MediaWiki API.

Good for categories like 'Heat pumps' / 'Air source heat pumps' — mostly unit
photos, few nameplate close-ups. Sets a descriptive User-Agent per Wikimedia's
polite-use policy.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import ImageRecord, append_manifest, load_queries

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "field-tech-copilot-research/0.1 (contact: alka.sv54@gmail.com)"
RATE_LIMIT_SECONDS = 1.0


def search(client: httpx.Client, query: str, limit: int = 20) -> list[dict]:
    search_resp = client.get(
        API,
        params={
            "action": "query", "format": "json", "list": "search",
            "srnamespace": 6, "srlimit": limit, "srsearch": query,
        },
        timeout=30.0,
    )
    search_resp.raise_for_status()
    titles = [hit["title"] for hit in search_resp.json().get("query", {}).get("search", [])]
    if not titles:
        return []

    info_resp = client.get(
        API,
        params={
            "action": "query", "format": "json", "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "titles": "|".join(titles),
        },
        timeout=30.0,
    )
    info_resp.raise_for_status()
    pages = info_resp.json().get("query", {}).get("pages", {})
    out = []
    for page in pages.values():
        for ii in page.get("imageinfo", []):
            meta = ii.get("extmetadata", {})
            out.append(
                {
                    "url": ii.get("url", ""),
                    "descriptionurl": ii.get("descriptionurl", ""),
                    "width": ii.get("width", 0),
                    "height": ii.get("height", 0),
                    "license": meta.get("LicenseShortName", {}).get("value", ""),
                    "license_url": meta.get("LicenseUrl", {}).get("value", ""),
                    "attribution": meta.get("Artist", {}).get("value", ""),
                }
            )
    return out


def main(limit_queries: int | None = None) -> None:
    sources_yaml = Path(__file__).resolve().parents[2] / "sources.yaml"
    queries = load_queries(sources_yaml)
    if limit_queries:
        queries = queries[:limit_queries]

    records = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
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
                        provider="wikimedia",
                        image_url=r["url"],
                        source_page=r["descriptionurl"],
                        license=r["license"],
                        license_url=r["license_url"],
                        attribution=r["attribution"],
                        width=r["width"],
                        height=r["height"],
                    )
                )
            print(f"[ok] {query!r}: {len(results)} results")
            time.sleep(RATE_LIMIT_SECONDS)

    append_manifest(records)
    print(f"Wrote {len(records)} records to images_manifest.csv")


if __name__ == "__main__":
    main()
