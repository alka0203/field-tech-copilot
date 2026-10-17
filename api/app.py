"""FastAPI service — HVAC field-tech copilot.

Two query modes:
  POST /query        — text override (brand + model + code)
  POST /query/image  — multipart image upload; runs VLM extraction first

GET  /health         — liveness check

Run locally:
  export GEMINI_API_KEY=...
  uvicorn api.app:app --reload --app-dir .

Deploy (Fly.io):
  fly deploy
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the scripts/infer module importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "infer"))

from copilot import generate_answer, retrieve, vlm_extract  # noqa: E402

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HVAC Field-Tech Copilot",
    description=(
        "Given a manufacturer, model family, and error code — returns the fault "
        "name, likely causes, and remedy steps grounded in the manufacturer's "
        "own service manual. Optionally accepts a nameplate/display photo and "
        "extracts brand/model/code via VLM before the RAG lookup."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TextQueryRequest(BaseModel):
    brand: str
    model_family: str = ""
    error_code: str = ""

    model_config = {"json_schema_extra": {
        "example": {"brand": "carrier", "model_family": "40MAQ", "error_code": "E1"}
    }}


class CopilotResponse(BaseModel):
    brand: str
    model_family: str
    error_code: str
    fault_name: str
    likely_causes: list[str]
    remedy_steps: list[str]
    source_reference: str
    confidence: str
    vlm_confidence: Optional[str] = None   # set when image mode was used
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=CopilotResponse)
def query_text(req: TextQueryRequest):
    """Look up an error code by brand / model family / code (no image)."""
    brand = req.brand.lower().strip()
    model_family = req.model_family.strip()
    error_code = req.error_code.strip().upper()

    if not brand and not error_code:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'brand' or 'error_code' must be provided.",
        )

    chunks = retrieve(brand, model_family, error_code)
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant context found in the RAG index for these parameters.",
        )

    answer = generate_answer(brand, model_family, error_code, chunks)

    if "error" in answer:
        raise HTTPException(status_code=500, detail=answer["error"])

    return CopilotResponse(
        brand=answer.get("brand", brand),
        model_family=answer.get("model_family", model_family),
        error_code=answer.get("error_code", error_code),
        fault_name=answer.get("fault_name", ""),
        likely_causes=answer.get("likely_causes", []),
        remedy_steps=answer.get("remedy_steps", []),
        source_reference=answer.get("source_reference", ""),
        confidence=answer.get("confidence", "low"),
        note=answer.get("note") or answer.get("_note"),
    )


@app.post("/query/image", response_model=CopilotResponse)
async def query_image(image: UploadFile = File(...)):
    """Accept a photo of a nameplate or error display; extract brand/model/code
    via Gemini VLM, then run the RAG lookup."""
    # Vision step lives in api/vision.py + scripts/vision/: EXIF fix/downscale/quality,
    # schema-constrained Gemini (falls back to local OCR if no key/quota), normalisation,
    # OCR cross-check. Returns the contract `vision` object.
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse

    from api.vision import analyze_image_bytes
    from scripts.vision import pipeline as _vp

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    try:
        vision, extras = await run_in_threadpool(analyze_image_bytes, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    def _fail(status: int, detail: str):
        return JSONResponse(status_code=status, content={"detail": detail, "vision": vision})

    if extras.get("unavailable"):
        return _fail(503, "Image mode unavailable: no GEMINI_API_KEY and local OCR not installed.")

    brand = vision["brand"].lower().strip()
    model_family = vision["model_family"].strip()
    error_code = vision["error_code"].strip().upper()
    vlm_confidence = _vp.overall_confidence(vision)

    if not brand and not error_code:
        return _fail(422, "Could not read a brand or error code from the image. "
                          + " ".join(vision["warnings"][:3]))

    chunks = await run_in_threadpool(retrieve, brand, model_family, error_code)
    if not chunks:
        return _fail(404, (
            f"Read brand={brand!r} model={model_family!r} "
            f"code={error_code!r} but no matching context found in the RAG index."
        ))

    answer = await run_in_threadpool(generate_answer, brand, model_family, error_code, chunks)

    if "error" in answer:
        return _fail(500, answer["error"])

    resp = CopilotResponse(
        brand=answer.get("brand", brand),
        model_family=answer.get("model_family", model_family),
        error_code=answer.get("error_code", error_code),
        fault_name=answer.get("fault_name", ""),
        likely_causes=answer.get("likely_causes", []),
        remedy_steps=answer.get("remedy_steps", []),
        source_reference=answer.get("source_reference", ""),
        confidence=answer.get("confidence", "low"),
        vlm_confidence=vlm_confidence,
        note=answer.get("note") or answer.get("_note"),
    )
    # CopilotResponse has no `vision` field; return JSON directly so the extra key is kept.
    return JSONResponse(content={**resp.model_dump(), "vision": vision})


# ---------------------------------------------------------------------------
# Modular routers (api/speech.py, api/vision.py) + static UI (ui/)
# Mounted last so the "/" static mount never shadows an API route.
# ---------------------------------------------------------------------------

for _name in ("speech", "vision"):
    if importlib.util.find_spec(f"api.{_name}"):
        app.include_router(importlib.import_module(f"api.{_name}").router)

if (REPO / "ui").is_dir():
    app.mount("/", StaticFiles(directory=REPO / "ui", html=True), name="ui")
