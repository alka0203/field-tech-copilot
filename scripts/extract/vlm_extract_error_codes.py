"""Sends each candidate error-code page (from find_error_pages.py) to a vision
LLM with a strict JSON schema, and writes error_codes.jsonl.

Every row carries source_pdf + page so a human can verify against the
original manual. Requires ANTHROPIC_API_KEY.

Usage:
  export ANTHROPIC_API_KEY=...
  python scripts/extract/vlm_extract_error_codes.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import anthropic

ERROR_PAGES_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "error_pages"
INDEX_PATH = ERROR_PAGES_DIR / "error_pages_index.json"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "error_codes.jsonl"
MODEL = "claude-sonnet-5"

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


def extract_page(client: anthropic.Anthropic, png_path: Path, brand: str) -> list[dict]:
    image_b64 = base64.standard_b64encode(png_path.read_bytes()).decode("utf-8")
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": f"Brand: {brand}\n\n{SCHEMA_PROMPT}"},
                ],
            }
        ],
    )
    text = message.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[warn] non-JSON response for {png_path}, skipping: {text[:200]}", file=sys.stderr)
        return []


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set — refusing to run paid VLM calls.", file=sys.stderr)
        sys.exit(1)
    if not INDEX_PATH.exists():
        print(f"No index at {INDEX_PATH} — run find_error_pages.py first.", file=sys.stderr)
        sys.exit(1)

    index = json.loads(INDEX_PATH.read_text())
    client = anthropic.Anthropic()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with OUT_PATH.open("w") as out_f:
        for entry in index:
            png_path = ERROR_PAGES_DIR.parents[0] / entry["png_path"]
            try:
                codes = extract_page(client, png_path, entry["brand"])
            except anthropic.APIError as e:
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
