"""Build ChromaDB RAG index from error_codes.jsonl + Docling markdown.

Two chunk types:
  error_table   — one chunk per structured error-code record (exact lookup)
  troubleshooting — 500-token sliding windows from service manual prose

Usage:
  python scripts/rag/build_index.py [--reset]

Flags:
  --reset   Drop and rebuild the collection from scratch.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

REPO = Path(__file__).resolve().parents[2]
ERROR_CODES_PATH = REPO / "data" / "manifests" / "error_codes.jsonl"
DOCLING_DIR = REPO / "data" / "raw" / "docling"
CHROMA_DIR = REPO / "data" / "chroma"

EMBED_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "hvac_manuals"
CHUNK_CHARS = 1800   # ~450 tokens at ~4 chars/token
OVERLAP_CHARS = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk_text(text: str, chunk_size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split text into overlapping character windows."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c.strip() for c in chunks if c.strip()]


def _clean_md(text: str) -> str:
    """Strip image placeholders and excessive blank lines."""
    text = re.sub(r'<!-- image -->', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Chunk builders
# ---------------------------------------------------------------------------

def error_table_chunks() -> list[tuple[str, dict, str]]:
    """Yields (text, metadata, id) for each error-code record."""
    if not ERROR_CODES_PATH.exists():
        print(f"[warn] {ERROR_CODES_PATH} not found — skipping error_table chunks", file=sys.stderr)
        return []

    out = []
    for i, line in enumerate(ERROR_CODES_PATH.read_text().splitlines()):
        if not line.strip():
            continue
        rec = json.loads(line)
        causes = "; ".join(rec.get("probable_causes") or [])
        steps = "; ".join(rec.get("remedy_steps") or [])
        text = (
            f"Brand: {rec['brand']}\n"
            f"Model family: {rec['model_family']}\n"
            f"Error code: {rec['code']}\n"
            f"Display type: {rec.get('display_type', 'unknown')}\n"
            f"Description: {rec['description']}\n"
            + (f"Probable causes: {causes}\n" if causes else "")
            + (f"Remedy steps: {steps}\n" if steps else "")
        ).strip()
        meta = {
            "chunk_type": "error_table",
            "brand": rec["brand"],
            "model_family": rec["model_family"],
            "code": rec["code"],
            "source_pdf": rec.get("source_pdf", ""),
        }
        chunk_id = f"ec_{rec['brand']}_{rec['model_family']}_{rec['code']}_{i}"
        out.append((text, meta, chunk_id))
    return out


def troubleshooting_chunks() -> list[tuple[str, dict, str]]:
    """Yields (text, metadata, id) for sliding-window prose chunks from Docling markdown."""
    out = []
    if not DOCLING_DIR.exists():
        return out
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
            text = _clean_md(md_path.read_text(encoding="utf-8"))
            doc_id = doc_dir.name
            for j, chunk in enumerate(_chunk_text(text)):
                meta = {
                    "chunk_type": "troubleshooting",
                    "brand": brand,
                    "model_family": "unknown",
                    "code": "",
                    "source_pdf": doc_id,
                }
                out.append((chunk, meta, f"ts_{brand}_{doc_id}_{j}"))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop and rebuild collection")
    args = parser.parse_args()

    print(f"Loading embedding model ({EMBED_MODEL}) …")
    embedder = SentenceTransformer(EMBED_MODEL)

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if args.reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print("[reset] Dropped existing collection.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # Gather all chunks
    chunks = error_table_chunks() + troubleshooting_chunks()
    if not chunks:
        print("No chunks found — nothing to index.", file=sys.stderr)
        sys.exit(1)

    # Filter out IDs already in the collection (idempotent re-runs)
    existing_ids = set(collection.get(include=[])["ids"])
    new_chunks = [(t, m, cid) for t, m, cid in chunks if cid not in existing_ids]
    print(f"Total chunks: {len(chunks)}  |  New: {len(new_chunks)}  |  Already indexed: {len(existing_ids)}")
    if not new_chunks:
        print("Nothing new to add.")
        return

    # Batch embed + upsert (ChromaDB recommends ≤5000 per batch)
    BATCH = 256
    for start in range(0, len(new_chunks), BATCH):
        batch = new_chunks[start : start + BATCH]
        texts = [t for t, _, _ in batch]
        metas = [m for _, m, _ in batch]
        ids   = [cid for _, _, cid in batch]
        embeddings = embedder.encode(texts, show_progress_bar=False).tolist()
        collection.add(documents=texts, embeddings=embeddings, metadatas=metas, ids=ids)
        print(f"  indexed {start + len(batch)}/{len(new_chunks)}")

    print(f"\nDone. Collection '{COLLECTION_NAME}' now has {collection.count()} chunks.")


if __name__ == "__main__":
    main()
