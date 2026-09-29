"""Thin end-to-end inference: photo → model ID + error code explanation.

Two modes:
  1. Image mode (--image <path>): sends photo to Gemini VLM to extract
     brand / model_family / error_code, then looks up in ChromaDB RAG index.
  2. Override mode (--brand --model --code): skip VLM, query RAG directly.
     Useful for testing the retrieval + answer path without an image.

Usage:
  # Image mode (requires GEMINI_API_KEY)
  export GEMINI_API_KEY=...
  python scripts/infer/copilot.py --image /path/to/photo.jpg

  # Override mode (no API key needed)
  python scripts/infer/copilot.py --brand carrier --model 38MAQ --code E1

Output: JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

REPO = Path(__file__).resolve().parents[2]
CHROMA_DIR = REPO / "data" / "chroma"
COLLECTION_NAME = "hvac_manuals"
EMBED_MODEL = "all-MiniLM-L6-v2"
GEMINI_MODEL = "gemini-3.8-flash"
TOP_K = 5

# ---------------------------------------------------------------------------
# VLM step — extract brand / model / code from image
# ---------------------------------------------------------------------------

NAMEPLATE_PROMPT = """You are analyzing a photo taken by an HVAC field technician.
The photo shows either:
  (a) a unit nameplate / data label, or
  (b) an error/fault code displayed on an LCD, LED, or 7-segment display.

Extract exactly these fields and return ONLY a JSON object, no other text:
{
  "brand": string,          // manufacturer name, e.g. "carrier", "mitsubishi", "daikin"
  "model_family": string,   // model series from nameplate, e.g. "38MAQ", "MSZ-GL", "" if not visible
  "error_code": string,     // error/fault code shown on display, e.g. "E1", "45", "" if not visible
  "confidence": "high"|"medium"|"low"
}

Use lowercase for brand. If a field is not legible or not present, use "".
Do NOT guess — only extract what is clearly visible."""


def vlm_extract(image_path: Path) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[error] GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    img_bytes = image_path.read_bytes()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    image_part = types.Part.from_bytes(data=img_bytes, mime_type=mime)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[NAMEPLATE_PROMPT, image_part],
    )
    text = response.text.strip()
    text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.DOTALL)
    return json.loads(text)


# ---------------------------------------------------------------------------
# RAG retrieval
# ---------------------------------------------------------------------------

_embedder: SentenceTransformer | None = None
_collection: chromadb.Collection | None = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        if not CHROMA_DIR.exists():
            print(f"[error] ChromaDB not found at {CHROMA_DIR}. Run scripts/rag/build_index.py first.", file=sys.stderr)
            sys.exit(1)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def retrieve(brand: str, model_family: str, error_code: str) -> list[dict]:
    """Query ChromaDB. Prefers exact error_table hits, falls back to semantic."""
    collection = _get_collection()
    embedder = _get_embedder()

    query = f"Brand: {brand}  Model: {model_family}  Error code: {error_code}"
    embedding = embedder.encode([query])[0].tolist()

    # Broad semantic search
    results = collection.query(
        query_embeddings=[embedding],
        n_results=TOP_K,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({"text": doc, "meta": meta, "score": round(1 - dist, 4)})

    # Boost: exact error_table hit for this code
    if error_code:
        exact = collection.get(
            where={"$and": [{"chunk_type": "error_table"}, {"code": error_code.upper()}]},
            include=["documents", "metadatas"],
        )
        for doc, meta in zip(exact["documents"], exact["metadatas"]):
            # Prepend if not already in results
            if not any(c["text"] == doc for c in chunks):
                chunks.insert(0, {"text": doc, "meta": meta, "score": 1.0})

    return chunks[:TOP_K]


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def _rag_fallback(brand: str, model_family: str, error_code: str, chunks: list[dict]) -> dict:
    """Extract answer directly from best RAG chunk without LLM synthesis."""
    best = next((c for c in chunks if c["meta"].get("chunk_type") == "error_table"), chunks[0] if chunks else None)
    if not best:
        return {"error": "No relevant context found."}
    text = best["text"]

    def _field(label: str) -> str:
        m = re.search(rf"^{label}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    causes_raw = _field("probable causes")
    return {
        "brand": brand, "model_family": model_family, "error_code": error_code,
        "fault_name": _field("description"),
        "likely_causes": [c.strip() for c in causes_raw.split(";") if c.strip()],
        "remedy_steps": [],
        "source_reference": best["meta"].get("source_pdf", ""),
        "confidence": "medium",
        "_note": "LLM synthesis unavailable (quota exhausted) — direct RAG extraction",
    }


ANSWER_PROMPT_TMPL = """You are an expert HVAC service advisor. A field technician needs help.

Technician's unit: Brand={brand}, Model={model_family}, Error code={error_code}

Retrieved context from the manufacturer's service manual:
---
{context}
---

Using ONLY the information above (do not add knowledge not present in the context),
return a JSON object with exactly these fields:
{{
  "brand": string,
  "model_family": string,
  "error_code": string,
  "fault_name": string,
  "likely_causes": [string],
  "remedy_steps": [string],
  "source_reference": string,   // source_pdf value from context, or "" if not present
  "confidence": "high"|"medium"|"low"
}}

If the context does not contain enough information for a field, use "" or [].
Return ONLY the JSON object."""


def generate_answer(brand: str, model_family: str, error_code: str, chunks: list[dict]) -> dict:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        # Return what we have from RAG without LLM synthesis
        best = next((c for c in chunks if c["meta"].get("chunk_type") == "error_table"), None)
        if best:
            text = best["text"]
            def _field(label: str) -> str:
                m = re.search(rf"^{label}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
                return m.group(1).strip() if m else ""
            causes_raw = _field("probable causes")
            return {
                "brand": brand, "model_family": model_family, "error_code": error_code,
                "fault_name": _field("description"),
                "likely_causes": [c.strip() for c in causes_raw.split(";") if c.strip()],
                "remedy_steps": [],
                "source_reference": best["meta"].get("source_pdf", ""),
                "confidence": "medium",
                "note": "LLM synthesis skipped (no GEMINI_API_KEY) — RAG direct extract",
            }
        return {"error": "No relevant context found and no GEMINI_API_KEY for synthesis."}

    context = "\n\n---\n\n".join(c["text"] for c in chunks)
    prompt = ANSWER_PROMPT_TMPL.format(
        brand=brand, model_family=model_family, error_code=error_code, context=context
    )
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt])
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            print("[warn] Gemini quota exhausted — falling back to direct RAG extraction", file=sys.stderr)
            return _rag_fallback(brand, model_family, error_code, chunks)
        raise
    text = response.text.strip()
    text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.DOTALL)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="HVAC field-tech copilot — identify + explain error codes.")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--image", metavar="PATH", help="Path to a photo of the unit/display")
    grp.add_argument("--brand", metavar="NAME", help="Override: brand name (use with --model and --code)")
    parser.add_argument("--model", metavar="FAMILY", default="", help="Override: model family")
    parser.add_argument("--code", metavar="CODE", default="", help="Override: error code")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM answer generation (RAG only)")
    args = parser.parse_args()

    # Step 1 — identify brand/model/code
    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"[error] Image not found: {image_path}", file=sys.stderr)
            sys.exit(1)
        print("[1/3] Running VLM nameplate/display extraction …", file=sys.stderr)
        vlm_result = vlm_extract(image_path)
        print(f"      VLM: {vlm_result}", file=sys.stderr)
        brand = vlm_result.get("brand", "").lower().strip()
        model_family = vlm_result.get("model_family", "").strip()
        error_code = vlm_result.get("error_code", "").strip().upper()
    else:
        brand = args.brand.lower().strip()
        model_family = args.model.strip()
        error_code = args.code.strip().upper()

    if not brand and not error_code:
        print("[error] Could not determine brand or error code. Nothing to look up.", file=sys.stderr)
        sys.exit(1)

    # Step 2 — RAG retrieval
    print(f"[2/3] Retrieving context for brand={brand!r} model={model_family!r} code={error_code!r} …", file=sys.stderr)
    chunks = retrieve(brand, model_family, error_code)
    print(f"      Found {len(chunks)} chunks (top score: {chunks[0]['score'] if chunks else 'n/a'})", file=sys.stderr)

    if not chunks:
        print(json.dumps({"error": "No relevant context found in the RAG index."}))
        sys.exit(0)

    # Step 3 — answer generation
    if args.no_llm:
        print(json.dumps({"brand": brand, "model_family": model_family, "error_code": error_code,
                          "chunks": [c["text"][:300] for c in chunks]}, indent=2))
        return

    print("[3/3] Generating grounded answer …", file=sys.stderr)
    answer = generate_answer(brand, model_family, error_code, chunks)
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
