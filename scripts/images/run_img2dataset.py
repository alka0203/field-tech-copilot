"""Downloads images_manifest.csv into data/raw/images/ (gitignored) via img2dataset.

img2dataset skips images whose X-Robots-Tag says noai/noimageai/noindex/
noimageindex by default — leave that behavior on.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from img2dataset import download

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "manifests" / "images_manifest.csv"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "images"
URL_LIST_TMP = Path(__file__).resolve().parents[2] / "data" / "raw" / "_img2dataset_urls.txt"


def main() -> None:
    df = pd.read_csv(MANIFEST)
    urls = df["image_url"].dropna().drop_duplicates()
    URL_LIST_TMP.parent.mkdir(parents=True, exist_ok=True)
    urls.to_csv(URL_LIST_TMP, index=False, header=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    download(
        url_list=str(URL_LIST_TMP),
        output_folder=str(OUT_DIR),
        input_format="txt",
        output_format="files",
        resize_mode="no",
        thread_count=8,
        number_sample_per_shard=1000,
    )
    print(f"Downloaded {len(urls)} candidate images to {OUT_DIR}")


if __name__ == "__main__":
    main()
