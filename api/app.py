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

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY not set — image mode unavailable.",
        )

    # Write the upload to a temp file (VLM needs a path)
    suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await image.read())
        tmp_path = Path(tmp.name)

    try:
        vlm_result = vlm_extract(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    brand = vlm_result.get("brand", "").lower().strip()
    model_family = vlm_result.get("model_family", "").strip()
    error_code = vlm_result.get("error_code", "").strip().upper()
    vlm_confidence = vlm_result.get("confidence", "low")

    if not brand and not error_code:
        raise HTTPException(
            status_code=422,
            detail=(
                "VLM could not extract brand or error code from the image. "
                f"Raw VLM result: {vlm_result}"
            ),
        )

    chunks = retrieve(brand, model_family, error_code)
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=(
                f"VLM extracted brand={brand!r} model={model_family!r} "
                f"code={error_code!r} but no matching context found in the RAG index."
            ),
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
        vlm_confidence=vlm_confidence,
        note=answer.get("note") or answer.get("_note"),
    )
