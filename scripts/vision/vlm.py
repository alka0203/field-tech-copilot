"""Schema-constrained Gemini extraction with per-field confidence.

Differences from the original `vlm_extract` prompt-and-parse approach:
  * response_mime_type=application/json + response_schema (enums for
    image_type / confidence), so no regex-stripping of code fences;
  * transcribe-then-extract: the schema asks for `visible_text` BEFORE the
    structured fields, so the model commits to what it literally sees;
  * explicit refusal protocol: unreadable plate => image_type "unreadable"
    and every field empty (CONTEXT.md eval case #14); no inference from
    cabinet shape, colour, or typical product lines;
  * temperature 0.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[2]
GEMINI_MODEL = os.environ.get("VISION_GEMINI_MODEL", "gemini-3.7-flash")

Conf = Literal["high", "medium", "low"]


class FieldConfidence(BaseModel):
    brand: Conf
    model_family: Conf
    error_code: Conf


class VlmReading(BaseModel):
    # Order matters: transcription first, decisions after.
    visible_text: str = Field(description="Verbatim text/characters you can actually read in the photo, "
                                          "separated by ' | '. Empty string if none is legible.")
    image_type: Literal["nameplate", "error_display", "unit", "other", "unreadable"]
    brand: str = Field(description="lowercase manufacturer name printed in the photo, or ''")
    model_family: str = Field(description="model series read from a printed model string, e.g. '40MAQ', 'MXZ', 'MSZ-FH', or ''")
    model_number: str = Field(description="full model string exactly as printed, or ''")
    error_code: str = Field(description="error/fault code shown on a display, e.g. 'E1', 'U4', 'F28', '45', or ''")
    field_confidence: FieldConfidence
    refusal_reason: str = Field(description="If image_type is 'unreadable' or a field was withheld, one short sentence why; else ''")


PROMPT = """You are the vision step of an HVAC field-technician copilot. Look at the photo and report ONLY what is physically legible in it.

Classify image_type:
- "nameplate": a data/rating label with printed manufacturer/model text
- "error_display": an LCD/LED/7-segment display or remote screen showing a code
- "unit": an HVAC unit or part with no legible label or code
- "other": not HVAC-related
- "unreadable": a nameplate or display is present but the text is too rusted, blurred, dark, glared or damaged to read

Rules (strict):
1. Transcribe first (visible_text), then fill fields from that transcription only.
2. NEVER guess, infer, or complete characters. Do not identify a model from cabinet shape, colour, or what is typical for a brand. If you cannot read a field, return "".
3. If the nameplate/display is unreadable, set image_type to "unreadable", leave brand, model_family, model_number and error_code as "", set every confidence to "low", and explain briefly in refusal_reason.
4. brand: lowercase, as printed ("carrier", "daikin", "mitsubishi"). model_family: the series prefix of the printed model string (e.g. "MXZ-4C36NA" -> "MXZ", "40MAQ0361" -> "40MAQ", "MSZ-FH12NA" -> "MSZ-FH").
5. error_code: only a fault code shown on a display (e.g. E1, U4, P8, F28, L3, H6, 45). Never take a code from a model number, serial number or voltage line.
6. field_confidence: "high" = every character clearly legible; "medium" = legible but some character could be confused (0/O, 1/I, 5/S, 8/B, 2/Z) or partly obscured; "low" = a best-effort reading. If a field is "", mark its confidence "low".
"""


class VlmUnavailable(RuntimeError):
    """No key, quota exhausted, or service down. Callers fall back to local OCR."""


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv(REPO / ".env")
            key = os.environ.get("GEMINI_API_KEY", "")
        except Exception:  # noqa: BLE001
            pass
    return key


def available() -> bool:
    return bool(api_key())


def extract(jpeg_bytes: bytes, retries: int = 1, timeout_s: int = 25, mime: str = "image/jpeg") -> dict:
    key = api_key()
    if not key:
        raise VlmUnavailable("GEMINI_API_KEY not set")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_s * 1000))
    part = types.Part.from_bytes(data=jpeg_bytes, mime_type=mime)
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=VlmReading,
        temperature=0.0,
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=[PROMPT, part], config=cfg)
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, VlmReading):
                return parsed.model_dump()
            return VlmReading.model_validate_json(resp.text).model_dump()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            last = e
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                raise VlmUnavailable("Gemini quota/rate limit (429)") from e
            if "503" in msg or "UNAVAILABLE" in msg:           # fast failure: one short retry
                if attempt < retries:
                    time.sleep(2 * (2 ** attempt))
                    continue
                raise VlmUnavailable("Gemini overloaded (503)") from e
            if "timed out" in msg.lower() or "deadline" in msg.lower():   # slow failure: do not retry, fall back now
                raise VlmUnavailable("Gemini timed out") from e
            raise VlmUnavailable(f"Gemini call failed: {msg[:100]}") from e
    raise VlmUnavailable(f"Gemini failed after retries: {last}")
