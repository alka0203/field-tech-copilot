"""Locates likely error-code pages in each manual by keyword search over the
Docling Markdown output, and renders just those pages to PNG (PyMuPDF,
200 dpi) for the vision-LLM extraction pass.

Output: data/raw/error_pages/<brand>/<doc_id>/page_<n>.png
Also writes error_pages_index.json listing which pages matched which keyword,
so vlm_extract_error_codes.py knows what to send.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

DOCLING_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "docling"
RAW_MANUALS = Path(__file__).resolve().parents[2] / "data" / "raw" / "manuals"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "error_pages"

KEYWORDS = [
    "error code", "malfunction", "fault", "event message", "blink",
    r"\bE\d\b", r"\bU\d\b", r"\bP\d\b", r"\bF\d\d?\b",
]
KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)
DPI = 200


def find_pdf_for_doc(brand: str, doc_id: str) -> Path | None:
    candidate = RAW_MANUALS / brand / f"{doc_id}.pdf"
    return candidate if candidate.exists() else None


def main() -> None:
    index: list[dict] = []
    if not DOCLING_DIR.exists():
        print(f"No Docling output at {DOCLING_DIR} — run run_docling.py first.")
        return

    for brand_dir in DOCLING_DIR.iterdir():
        if not brand_dir.is_dir():
            continue
        for doc_dir in brand_dir.iterdir():
            content_md = doc_dir / "content.md"
            if not content_md.exists():
                continue
            pdf_path = find_pdf_for_doc(brand_dir.name, doc_dir.name)
            if pdf_path is None:
                print(f"[skip] no source PDF for {brand_dir.name}/{doc_dir.name}")
                continue

            text = content_md.read_text()
            # Docling's markdown export doesn't carry page numbers, so cross-check
            # keyword hits against the raw PDF text per page instead.
            pdf = fitz.open(pdf_path)
            matched_pages = []
            for page_num, page in enumerate(pdf):
                page_text = page.get_text()
                hits = KEYWORD_RE.findall(page_text)
                if hits:
                    matched_pages.append((page_num, sorted(set(h.lower() for h in hits))))

            if not matched_pages:
                continue

            out_dir = OUT_DIR / brand_dir.name / doc_dir.name
            out_dir.mkdir(parents=True, exist_ok=True)
            for page_num, hits in matched_pages:
                page = pdf[page_num]
                pix = page.get_pixmap(dpi=DPI)
                png_path = out_dir / f"page_{page_num:03d}.png"
                pix.save(png_path)
                index.append(
                    {
                        "brand": brand_dir.name,
                        "doc_id": doc_dir.name,
                        "page": page_num,
                        "png_path": str(png_path.relative_to(OUT_DIR.parents[0])),
                        "matched_keywords": hits,
                        "source_pdf": str(pdf_path.relative_to(RAW_MANUALS.parents[0])),
                    }
                )
            print(f"[ok] {brand_dir.name}/{doc_dir.name}: {len(matched_pages)} candidate error-code pages")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "error_pages_index.json").write_text(json.dumps(index, indent=2))
    print(f"\nWrote {len(index)} candidate pages to error_pages_index.json")


if __name__ == "__main__":
    main()
