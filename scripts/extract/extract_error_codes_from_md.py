"""Extract error codes from Docling markdown output and write error_codes.jsonl.

Primary extraction path for PDF-sourced manuals — no API calls needed.
Reads data/raw/docling/<brand>/<doc_id>/content.md, finds tables and
per-code diagnosis sections, and emits structured records.

VLM extraction (vlm_extract_error_codes.py) supplements for image-only sources.

Usage:
  python scripts/extract/extract_error_codes_from_md.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DOCLING_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "docling"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "error_codes.jsonl"
MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "manuals_manifest.csv"

# Matches HVAC error codes: E0, F4, P0, EC, U4, H6, etc.
CODE_RE = re.compile(r'^([EFPHUC][0-9A-Z]{0,2})$')


# ---------------------------------------------------------------------------
# Markdown table helpers
# ---------------------------------------------------------------------------

def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _parse_table(table_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data_rows) from a block of pipe-table lines."""
    if len(table_lines) < 3:
        return [], []
    headers = _split_row(table_lines[0])
    rows = [_split_row(l) for l in table_lines[2:] if l.startswith('|')]
    return headers, rows


def _find_col(headers: list[str], *keywords: str) -> int:
    """Index of first header whose lowercased text contains any keyword."""
    for i, h in enumerate(headers):
        hl = h.lower()
        for kw in keywords:
            if kw in hl:
                return i
    return -1


# ---------------------------------------------------------------------------
# Extraction logic
# ---------------------------------------------------------------------------

def _from_summary_table(
    headers: list[str],
    rows: list[list[str]],
    brand: str,
    model_family: str,
    source_pdf: str,
) -> list[dict]:
    """Tables with a code column and a description column per row."""
    code_col = _find_col(headers, 'display', 'iu display')
    if code_col < 0:
        return []
    desc_col = _find_col(headers, 'status', 'problem', 'description', 'led status')
    if desc_col < 0:
        desc_col = 0 if code_col != 0 else 1

    out = []
    for row in rows:
        if len(row) <= code_col:
            continue
        code = row[code_col].strip()
        if not CODE_RE.match(code):
            continue
        desc = row[desc_col].strip() if desc_col < len(row) else ""
        out.append({
            "brand": brand, "model_family": model_family,
            "code": code, "display_type": "7seg", "description": desc,
            "probable_causes": [], "remedy_steps": [],
            "source_pdf": source_pdf, "page": None,
        })
    return out


def _from_led_flash_table(
    headers: list[str],
    rows: list[list[str]],
    brand: str,
    model_family: str,
    source_pdf: str,
) -> list[dict]:
    """Tables with FAULT | AMBER LED FLASH CODE | POSSIBLE CAUSE columns.

    Flash codes like '45' (4 blinks, pause, 5 blinks) are used as-is.
    Rows where FAULT is blank inherit the last non-blank fault name.
    """
    code_col = _find_col(headers, 'flash code', 'led flash', 'blink')
    fault_col = _find_col(headers, 'fault', 'description', 'problem')
    cause_col = _find_col(headers, 'cause', 'action', 'remedy')
    if code_col < 0 or fault_col < 0:
        return []

    out = []
    last_fault = ""
    for row in rows:
        if len(row) <= max(code_col, fault_col):
            continue
        fault = row[fault_col].strip()
        if fault:
            last_fault = fault
        code = row[code_col].strip()
        if not code or code.lower() in ('on solid, no flash', 'n/a', '-', ''):
            continue
        # Keep numeric flash codes as-is; skip non-code values
        if not re.match(r'^[\d,\s\*]+$', code) and not CODE_RE.match(code):
            continue
        # Normalize: strip trailing asterisks and spaces
        code = code.rstrip('* ')
        cause_raw = row[cause_col].strip() if cause_col >= 0 and cause_col < len(row) else ""
        causes = [s.strip() for s in re.split(r'[.]{2,}|(?<=[a-z])\.\s+(?=[A-Z])', cause_raw) if s.strip()]
        out.append({
            "brand": brand, "model_family": model_family,
            "code": code, "display_type": "led_blink",
            "description": last_fault or fault,
            "probable_causes": causes, "remedy_steps": [],
            "source_pdf": source_pdf, "page": None,
        })
    return out


def extract_from_md(
    md_path: Path, brand: str, model_family: str, source_pdf: str
) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    by_code: dict[str, dict] = {}

    # --- Pass 1: summary tables (code-per-row) ---
    i = 0
    while i < len(lines):
        if lines[i].startswith('|'):
            tbl = []
            while i < len(lines) and lines[i].startswith('|'):
                tbl.append(lines[i])
                i += 1
            headers, rows = _parse_table(tbl)
            for rec in _from_summary_table(headers, rows, brand, model_family, source_pdf):
                by_code.setdefault(rec["code"], rec)
            for rec in _from_led_flash_table(headers, rows, brand, model_family, source_pdf):
                by_code.setdefault(rec["code"], rec)
        else:
            i += 1

    # --- Pass 2: per-code 2-column diagnosis blocks ---
    # e.g. | Error Code | E1 |
    #       | Malfunction decision conditions | ... |
    #       | Supposed causes | ·wiring ·PCB |
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('|') and 'error code' in line.lower():
            cells = _split_row(line)
            if len(cells) >= 2:
                raw_codes = re.findall(r'\b([EFPHUC][0-9A-Z]{0,2})\b', cells[1])
                codes = [c for c in raw_codes if CODE_RE.match(c)]
                if codes:
                    conditions, causes = "", ""
                    j = i + 1
                    while j < len(lines) and lines[j].startswith('|'):
                        sc = _split_row(lines[j])
                        if len(sc) >= 2:
                            label, val = sc[0].lower(), sc[1]
                            if 'condition' in label or 'decision' in label:
                                conditions = val
                            elif 'cause' in label or 'reason' in label:
                                causes = val
                        j += 1
                    cause_list = [c.strip(' ·') for c in re.split(r'[·•]', causes) if c.strip(' ·')]
                    for code in codes:
                        if code in by_code:
                            if cause_list:
                                by_code[code]["probable_causes"] = cause_list
                        else:
                            # Pull description from nearest heading above
                            desc = conditions
                            for k in range(i - 1, max(0, i - 8), -1):
                                m = re.match(r'^#+\s+(.*)', lines[k])
                                if m:
                                    desc = m.group(1).strip()
                                    break
                            by_code[code] = {
                                "brand": brand, "model_family": model_family,
                                "code": code, "display_type": "7seg", "description": desc,
                                "probable_causes": cause_list, "remedy_steps": [],
                                "source_pdf": source_pdf, "page": None,
                            }
        i += 1

    return list(by_code.values())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not DOCLING_DIR.exists():
        print(f"No docling output at {DOCLING_DIR} — run run_docling.py first.", file=sys.stderr)
        sys.exit(1)

    # Load manifest to map sha256 prefix → (brand, model_family)
    meta: dict[str, tuple[str, str]] = {}
    if MANIFEST_PATH.exists():
        import csv
        with MANIFEST_PATH.open() as f:
            for row in csv.DictReader(f):
                meta[row["sha256"][:16]] = (row["brand"], row["model_family"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with OUT_PATH.open("w") as out_f:
        for brand_dir in sorted(DOCLING_DIR.iterdir()):
            if not brand_dir.is_dir():
                continue
            brand = brand_dir.name
            for doc_dir in sorted(brand_dir.iterdir()):
                if not doc_dir.is_dir():
                    continue
                md_path = doc_dir / "content.md"
                if not md_path.exists():
                    continue
                doc_id = doc_dir.name
                brand_meta, model_family = meta.get(doc_id, (brand, "unknown"))
                records = extract_from_md(md_path, brand_meta, model_family, source_pdf=doc_id)
                for rec in records:
                    out_f.write(json.dumps(rec) + "\n")
                    total += 1
                print(f"[ok] {brand}/{doc_id}: {len(records)} codes")

    print(f"\nWrote {total} error-code rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
