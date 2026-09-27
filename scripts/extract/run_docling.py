"""Runs Docling over every manual in data/raw/manuals/ and writes per-PDF
Markdown + table JSON + figure crops for the RAG index.

Output layout: data/raw/docling/<brand>/<sha256[:16]>/
  - content.md
  - tables.json
  - figures/*.png
"""
from __future__ import annotations

import json
from pathlib import Path

from docling.document_converter import DocumentConverter

RAW_MANUALS = Path(__file__).resolve().parents[2] / "data" / "raw" / "manuals"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "docling"


def process_pdf(converter: DocumentConverter, pdf_path: Path, brand: str) -> None:
    doc_id = pdf_path.stem  # sha256[:16], set by fetch_pdf_head_and_hash
    out = OUT_DIR / brand / doc_id
    out.mkdir(parents=True, exist_ok=True)

    result = converter.convert(str(pdf_path))
    doc = result.document

    (out / "content.md").write_text(doc.export_to_markdown())

    tables = [table.export_to_dataframe().to_dict(orient="records") for table in doc.tables]
    (out / "tables.json").write_text(json.dumps(tables, indent=2))

    figures_dir = out / "figures"
    figures_dir.mkdir(exist_ok=True)
    for i, picture in enumerate(doc.pictures):
        img = picture.get_image(doc)
        if img is not None:
            img.save(figures_dir / f"figure_{i:03d}.png")

    print(f"[ok] {brand}/{doc_id}: {len(doc.tables)} tables, {len(doc.pictures)} figures")


def main() -> None:
    converter = DocumentConverter()
    if not RAW_MANUALS.exists():
        print(f"No manuals found at {RAW_MANUALS} — run the manual spiders first.")
        return
    for brand_dir in RAW_MANUALS.iterdir():
        if not brand_dir.is_dir():
            continue
        for pdf_path in brand_dir.glob("*.pdf"):
            try:
                process_pdf(converter, pdf_path, brand_dir.name)
            except Exception as e:
                print(f"[fail] {pdf_path}: {e}")


if __name__ == "__main__":
    main()
