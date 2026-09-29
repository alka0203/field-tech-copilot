"""Sends each candidate error-code page (from find_error_pages.py) to a vision
LLM with a strict JSON schema, and writes error_codes.jsonl.

Every row carries source_pdf + page so a human can verify against the
original manual. Requires GEMINI_API_KEY.

Usage:
  export GEMINI_API_KEY=...
  python scripts/extract/vlm_extract_error_codes.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import google.generativeai as genai
import PIL.Image
import io

ERROR_PAGES_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "error_pages"
INDEX_PATH = ERROR_PAGES_DIR / "error_pages_index.json"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "error_codes.jsonl"
GEMINI_MODEL = "gemini-1.5-flash"

SCHEMA_PROMPT = """You are reading one page of an HVAC service manual. Extract every
distinct error/fault/malfunction code shown on this page as a JSON array. Each
element must match exactly this shape:

{
  "brand": string,
  "model_family": string,
  "code": string,             // e.g. "E1", "U4", "P9", "F28"
  "display_type": "7seg" | "led_blink" | "lcd" | "text" | "unknown",
  "description": string,      // what the code means
  "probable_causes": [string],
  "remedy_steps": [string]
}

If the page shows no error codes, return an empty array []. Only extract what
is actually printed on the page — do not infer codes from general HVAC
knowledge. Return ONLY the JSON array, no other text."""

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
model = genai.GenerativeModel(GEMINI_MODEL)


def extract_page(png_path: Path, brand: str) -> list[dict]:
    img = PIL.Image.open(io.BytesIO(png_path.read_bytes()))
    response = model.generate_content([f"Brand: {brand}\n\n{SCHEMA_PROMPT}", img])
    text = response.text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[warn] non-JSON response for {png_path}, skipping: {text[:200]}", file=sys.stderr)
        return []


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set — refusing to run paid VLM calls.", file=sys.stderr)
        sys.exit(1)
    if not INDEX_PATH.exists():
        print(f"No index at {INDEX_PATH} — run find_error_pages.py first.", file=sys.stderr)
        sys.exit(1)

    index = json.loads(INDEX_PATH.read_text())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with OUT_PATH.open("w") as out_f:
        for entry in index:
            png_path = ERROR_PAGES_DIR.parents[0] / entry["png_path"]
            try:
                codes = extract_page(png_path, entry["brand"])
            except Exception as e:
                print(f"[fail] {png_path}: {e}", file=sys.stderr)
                continue
            for code in codes:
                code["source_pdf"] = entry["source_pdf"]
                code["page"] = entry["page"]
                out_f.write(json.dumps(code) + "\n")
                written += 1
            print(f"[ok] {entry['brand']}/{entry['doc_id']} page {entry['page']}: {len(codes)} codes")

    print(f"\nWrote {written} error-code rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
