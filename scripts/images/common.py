"""Shared helpers for image-source fetchers: manifest schema + append."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "images_manifest.csv"
MANIFEST_FIELDS = [
    "brand", "model_family", "query", "provider", "image_url", "source_page",
    "license", "license_url", "attribution", "retrieved_at", "width", "height",
]


@dataclass
class ImageRecord:
    brand: str
    model_family: str
    query: str
    provider: str
    image_url: str
    source_page: str
    license: str = ""
    license_url: str = ""
    attribution: str = ""
    retrieved_at: str = ""
    width: int = 0
    height: int = 0

    def __post_init__(self) -> None:
        if not self.retrieved_at:
            self.retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_manifest(records: list[ImageRecord]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not MANIFEST_PATH.exists()
    with MANIFEST_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))


def load_queries(sources_yaml_path: Path) -> list[tuple[str, str, str]]:
    """Returns (brand, model_family, query_text) tuples fanned out from sources.yaml."""
    import yaml

    with sources_yaml_path.open() as f:
        cfg = yaml.safe_load(f)
    out = []
    for brand in cfg["brands"]:
        for family in brand["model_families"]:
            for query_type in cfg["image_query_types"]:
                out.append((brand["name"], family, f"{brand['display_name']} {family} {query_type}"))
    return out
