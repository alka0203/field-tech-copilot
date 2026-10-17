"""Vision endpoints: local quality check and vision-only analysis.

  POST /vision/quality  local OpenCV quality metrics, no API key, <300 ms
  POST /vision/analyze  preprocess + Gemini (schema-constrained) + local OCR cross-check, no RAG

`analyze_image_bytes` is shared with POST /query/image in api/app.py.
Heavy logic lives in scripts/vision/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.vision import pipeline, preprocess  # noqa: E402

router = APIRouter(tags=["vision"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def analyze_image_bytes(data: bytes, use_vlm: bool = True) -> tuple[dict, dict]:
    """Blocking; call via run_in_threadpool. Raises ValueError on undecodable input."""
    return pipeline.analyze(data, use_vlm=use_vlm)


async def _read_upload(image: UploadFile) -> bytes:
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image larger than 25 MB.")
    return data


@router.post("/vision/quality")
async def vision_quality(image: UploadFile = File(...)):
    """Local-only quality check (blur / brightness / glare / size). No API call."""
    data = await _read_upload(image)
    try:
        return await run_in_threadpool(preprocess.assess_bytes, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/vision/analyze")
async def vision_analyze(image: UploadFile = File(...)):
    """Vision step only (no RAG): the `vision` object plus the raw VLM dict."""
    data = await _read_upload(image)
    try:
        vision, extras = await run_in_threadpool(analyze_image_bytes, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {**vision, "raw": extras["raw"], "ocr": extras["ocr"], "timing_ms": extras["timing_ms"]}
