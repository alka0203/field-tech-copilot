"""Local OCR (RapidOCR / PP-OCR via onnxruntime) — optional and lazy.

Importing this module never imports rapidocr; the engine is created on first
use. If rapidocr isn't installed, `available()` is False and `read()` raises
OcrUnavailable, so the API still starts.

Used for (i) a no-quota fallback reading and (ii) cross-validating the VLM.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

from .normalize import (MODEL_STRING_RE, normalize_brand, normalize_error_code,
                        split_model, CODE_RE)

_engine = None
_lock = threading.Lock()


class OcrUnavailable(RuntimeError):
    pass


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("rapidocr") is not None


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            try:
                for name in ("RapidOCR", "rapidocr"):
                    logging.getLogger(name).setLevel(logging.ERROR)
                from rapidocr import RapidOCR
            except Exception as e:  # noqa: BLE001
                raise OcrUnavailable(f"rapidocr not installed: {e}") from e
            _engine = RapidOCR(params={"Global.log_level": "error"})
        return _engine


@dataclass
class OcrLine:
    text: str
    score: float


def _run(bgr: np.ndarray) -> list[OcrLine]:
    res = _get_engine()(bgr)
    if res is None or res.txts is None:
        return []
    return [OcrLine(t, float(s)) for t, s in zip(res.txts, res.scores)]


def _prep_for_ocr(bgr: np.ndarray) -> np.ndarray:
    """PP-OCR detectors want text >= ~20 px tall; upscale tiny crops (e.g. a
    zoomed-in display) and add a border so characters touching the edge are found."""
    import cv2

    h, w = bgr.shape[:2]
    if max(h, w) < 640:
        s = 640 / max(h, w)
        bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    pad = 24
    return cv2.copyMakeBorder(bgr, pad, pad, pad, pad, cv2.BORDER_REPLICATE)


def _useful(parsed: dict) -> bool:
    return bool(parsed["error_codes"] or parsed["models"] or parsed["brand"])


def read(bgr: np.ndarray, try_rotations: bool = True, min_score: float = 0.5) -> tuple[list[OcrLine], int]:
    """OCR an image, returning (lines, rotation_degrees_used).

    The engine's text-angle classifier only fixes 180 deg. Phone photos with
    stripped EXIF can be 90/270 deg off, so if 0 deg yields no *useful* parse
    (error code / model / brand) we also try 90 and 270 and keep the first
    rotation that does; otherwise the 0 deg lines are returned."""
    import cv2

    base = _prep_for_ocr(bgr)
    lines0 = [l for l in _run(base) if l.score >= min_score]
    if not try_rotations or _useful(parse(lines0)):
        return lines0, 0
    for deg, code in ((90, cv2.ROTATE_90_CLOCKWISE), (270, cv2.ROTATE_90_COUNTERCLOCKWISE)):
        lines = [l for l in _run(cv2.rotate(base, code)) if l.score >= min_score]
        if _useful(parse(lines)):
            return lines, deg
    return lines0, 0


# --- parsing OCR text into HVAC fields -------------------------------------

_BRAND_WORDS = ("carrier", "daikin", "mitsubishi", "bryant")
MAX_DISPLAY_LINES = 3     # an error display has little text; nameplates have many lines


def parse(lines: list[OcrLine]) -> dict:
    """Regex extraction of error code / model / brand from OCR lines."""
    texts = [l.text.strip() for l in lines if l.text.strip()]
    blob = " | ".join(texts)
    out: dict = {"error_codes": [], "models": [], "brand": "", "model_family": "",
                 "n_lines": len(texts), "lines": texts, "changes": []}

    low = blob.lower()
    for w in _BRAND_WORDS:
        if w in low:
            out["brand"] = normalize_brand(w)
            break

    seen = set()
    text = blob.upper().replace("—", "-").replace("–", "-")
    text = re.sub(r"\bMODEL(?:\s*(?:NO\.?|NUMBER))?[:\s]*", "MODEL ", text)   # OCR often glues the label to the value
    for m in MODEL_STRING_RE.finditer(text):
        s = m.group(0).strip("-/")
        if s not in seen:
            seen.add(s)
            out["models"].append(s)
    if out["models"]:
        best = max(out["models"], key=len)
        brand, fam = split_model(best)
        out["model_family"] = fam
        if not out["brand"]:
            out["brand"] = brand

    # Error codes: only in "display-like" images (few lines), whole-token match.
    if len(texts) <= MAX_DISPLAY_LINES:
        for t in texts:
            for tok in re.split(r"[\s,;|]+", t):
                if not tok or len(tok) > 4:
                    continue
                code, changes = normalize_error_code(tok)
                if code and CODE_RE.match(code) and (code not in out["error_codes"]):
                    # Pure-digit tokens are too ambiguous unless the line is the token
                    if code.isdigit() and len(texts) > 1:
                        continue
                    out["error_codes"].append(code)
                    out["changes"] += changes
    return out
