"""Four-stage filter over downloaded candidate images:
  1. exact dupes -> SHA-256
  2. near-dupes -> perceptual hash (Hamming distance <= 8)
  3. semantic dupes + relevance -> CLIP cosine similarity + zero-shot scoring
  4. resolution/legibility -> drop < 600px short side

Writes data/manifests/images_kept.csv (surviving candidates) and prints a
summary of how many were dropped at each stage, since that keep-rate is
itself a metric worth reporting.

CLIP is optional: pass --skip-clip to run stages 1/2/4 only (useful before
installing torch/open_clip).
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import imagehash
import pandas as pd
from PIL import Image

RAW_IMAGES = Path(__file__).resolve().parents[2] / "data" / "raw" / "images"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "images_kept.csv"

MIN_SHORT_SIDE = 600
PHASH_HAMMING_THRESHOLD = 8
CLIP_DUPLICATE_COSINE = 0.95
RELEVANCE_PROMPTS = [
    "a photo of an HVAC nameplate rating label",
    "a photo of an air conditioner outdoor unit",
    "an LCD or 7-segment error code display",
    "a remote controller for an air conditioner",
]
RELEVANCE_MIN_SCORE = 0.2  # zero-shot score against the best-matching relevant prompt


def iter_image_paths():
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        yield from RAW_IMAGES.rglob(ext)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage1_exact_dedupe(paths: list[Path]) -> list[Path]:
    seen = {}
    kept = []
    for p in paths:
        h = sha256_of(p)
        if h in seen:
            continue
        seen[h] = p
        kept.append(p)
    print(f"[stage1 exact] {len(paths)} -> {len(kept)}")
    return kept


def stage2_phash_dedupe(paths: list[Path]) -> list[Path]:
    hashes: list[tuple[Path, imagehash.ImageHash]] = []
    kept = []
    for p in paths:
        try:
            with Image.open(p) as img:
                h = imagehash.phash(img)
        except Exception:
            continue
        if any((h - existing) <= PHASH_HAMMING_THRESHOLD for _, existing in hashes):
            continue
        hashes.append((p, h))
        kept.append(p)
    print(f"[stage2 phash] {len(paths)} -> {len(kept)}")
    return kept


def stage3_clip_dedupe_and_relevance(paths: list[Path]) -> list[Path]:
    import open_clip
    import torch

    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    with torch.no_grad():
        text_tokens = tokenizer(RELEVANCE_PROMPTS)
        text_features = model.encode_text(text_tokens)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    embeddings: list[torch.Tensor] = []
    kept = []
    for p in paths:
        try:
            with Image.open(p) as img:
                image_input = preprocess(img.convert("RGB")).unsqueeze(0)
        except Exception:
            continue
        with torch.no_grad():
            feat = model.encode_image(image_input)
            feat /= feat.norm(dim=-1, keepdim=True)

        relevance = (feat @ text_features.T).max().item()
        if relevance < RELEVANCE_MIN_SCORE:
            continue

        if any((feat @ existing.T).item() >= CLIP_DUPLICATE_COSINE for existing in embeddings):
            continue

        embeddings.append(feat)
        kept.append(p)
    print(f"[stage3 clip] {len(paths)} -> {len(kept)}")
    return kept


def stage4_resolution_filter(paths: list[Path]) -> list[Path]:
    kept = []
    for p in paths:
        try:
            with Image.open(p) as img:
                if min(img.size) >= MIN_SHORT_SIDE:
                    kept.append(p)
        except Exception:
            continue
    print(f"[stage4 resolution] {len(paths)} -> {len(kept)}")
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-clip", action="store_true", help="Run stages 1/2/4 only.")
    args = parser.parse_args()

    if not RAW_IMAGES.exists():
        print(f"No raw images at {RAW_IMAGES} — run run_img2dataset.py first.")
        return

    paths = list(iter_image_paths())
    print(f"Starting from {len(paths)} raw candidates.")
    paths = stage1_exact_dedupe(paths)
    paths = stage2_phash_dedupe(paths)
    if not args.skip_clip:
        paths = stage3_clip_dedupe_and_relevance(paths)
    paths = stage4_resolution_filter(paths)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"path": [str(p) for p in paths]}).to_csv(OUT_PATH, index=False)
    print(f"\nKept {len(paths)} candidates -> {OUT_PATH}")


if __name__ == "__main__":
    main()
