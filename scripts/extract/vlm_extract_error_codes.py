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
import re
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

ERROR_PAGES_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "error_pages"
INDEX_PATH = ERROR_PAGES_DIR / "error_pages_index.json"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "error_codes.jsonl"
GEMINI_MODEL = "gemini-3.8-flash"

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

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def extract_page(png_path: Path, brand: str, retries: int = 3) -> list[dict]:
    png_bytes = png_path.read_bytes()
    image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    for attempt in range(retries):
        try:
            response = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[f"Brand: {brand}\n\n{SCHEMA_PROMPT}", image_part],
            )
            text = response.text.strip()
            # Strip ```json fences if present
            text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.DOTALL)
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[warn] non-JSON response for {png_path}: {text[:200]}", file=sys.stderr)
            return []
        except Exception as e:
            err = str(e)
            # Respect retryDelay hint from 429 responses
            retry_match = re.search(r'retryDelay.*?(\d+)s', err)
            if "503" in err or "UNAVAILABLE" in err:
                delay = min(30 * (2 ** attempt), 120)
                print(f"[retry] 503 on {png_path.name}, waiting {delay}s (attempt {attempt+1}/{retries})", file=sys.stderr)
                time.sleep(delay)
            elif "429" in err or "RESOURCE_EXHAUSTED" in err:
                delay = int(retry_match.group(1)) + 2 if retry_match else 60
                print(f"[retry] 429 on {png_path.name}, waiting {delay}s (attempt {attempt+1}/{retries})", file=sys.stderr)
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"Failed after {retries} retries: {png_path.name}")


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
