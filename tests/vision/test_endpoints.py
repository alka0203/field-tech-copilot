import time

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.vision import router
from scripts.vision import pipeline, sevenseg

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_quality_endpoint_no_key(monkeypatch, sharp_arr, make_jpeg):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    t = time.perf_counter()
    r = client.post("/vision/quality", files={"image": ("a.jpg", make_jpeg(sharp_arr), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"quality", "warnings"}
    assert set(body["quality"]) == {"blur_score", "brightness", "glare_fraction", "width", "height", "usable"}
    assert (time.perf_counter() - t) < 0.5


def test_quality_endpoint_flags_blur(sharp_arr, make_jpeg):
    blurred = cv2.GaussianBlur(sharp_arr, (0, 0), 8)
    r = client.post("/vision/quality", files={"image": ("a.jpg", make_jpeg(blurred), "image/jpeg")})
    assert r.json()["quality"]["usable"] is False and r.json()["warnings"]


def test_quality_endpoint_rejects_garbage():
    assert client.post("/vision/quality", files={"image": ("a.jpg", b"xx", "image/jpeg")}).status_code == 422
    assert client.post("/vision/quality", files={"image": ("a.jpg", b"", "image/jpeg")}).status_code == 400


def test_analyze_contract_without_gemini(monkeypatch, make_jpeg):
    """No key: falls back to local reader; response still has the full vision contract."""
    monkeypatch.setattr("scripts.vision.vlm.api_key", lambda: "")
    from scripts.vision.dataset import make_display
    img = cv2.cvtColor(make_display("P8", 7), cv2.COLOR_BGR2RGB)
    r = client.post("/vision/analyze", files={"image": ("a.jpg", make_jpeg(img), "image/jpeg")})
    assert r.status_code == 200
    b = r.json()
    for k in ("brand", "model_family", "error_code", "field_confidence", "image_type", "quality", "warnings", "preprocess", "raw"):
        assert k in b
    assert set(b["field_confidence"]) == {"brand", "model_family", "error_code"}
    assert all(v in ("high", "medium", "low") for v in b["field_confidence"].values())
    assert any("Gemini unavailable" in w or "GEMINI" in w for w in b["warnings"])


def _vlm(monkeypatch, raw):
    monkeypatch.setattr("scripts.vision.vlm.api_key", lambda: "k")
    monkeypatch.setattr("scripts.vision.vlm.extract", lambda *_a, **_k: raw)


def _png_bytes(make_jpeg):
    return make_jpeg(np.full((400, 600, 3), 128, np.uint8) + np.random.default_rng(0).integers(0, 60, (400, 600, 3), dtype=np.uint8))


def test_unreadable_forces_empty_fields(monkeypatch, make_jpeg):
    _vlm(monkeypatch, {"image_type": "unreadable", "brand": "carrier", "model_family": "40MAQ", "error_code": "E1",
                       "field_confidence": {"brand": "high", "model_family": "high", "error_code": "high"},
                       "refusal_reason": "rusted"})
    v, _ = pipeline.analyze(_png_bytes(make_jpeg), use_ocr=False)
    assert v["image_type"] == "unreadable"
    assert v["brand"] == v["model_family"] == v["error_code"] == ""
    assert set(v["field_confidence"].values()) == {"low"}
    assert any("discarded" in w for w in v["warnings"])


def test_vlm_code_normalised_and_logged(monkeypatch, make_jpeg):
    _vlm(monkeypatch, {"image_type": "error_display", "brand": "Mitsubishi Electric", "model_family": "", "error_code": "P8O",
                       "field_confidence": {"brand": "high", "model_family": "low", "error_code": "high"}})
    v, _ = pipeline.analyze(_png_bytes(make_jpeg), use_ocr=False)
    assert v["error_code"] == "P80" and v["brand"] == "mitsubishi"
    assert v["field_confidence"]["error_code"] == "medium"        # lowered one step
    assert any("'O'->'0'" in w for w in v["warnings"])


def test_ocr_disagreement_lowers_confidence(monkeypatch, make_jpeg):
    _vlm(monkeypatch, {"image_type": "error_display", "brand": "", "model_family": "", "error_code": "E1",
                       "field_confidence": {"brand": "low", "model_family": "low", "error_code": "high"}})
    fake = {"lines": ["U4"], "error_codes": ["U4"], "seg_code": "", "ocr_codes": ["U4"], "models": [], "brand": "",
            "model_family": "", "rotation": 0, "scores": [0.9], "ms": 1, "n_lines": 1, "changes": []}
    monkeypatch.setattr(pipeline, "_ocr_safe", lambda bgr: (fake, ""))
    v, _ = pipeline.analyze(_png_bytes(make_jpeg))
    assert v["field_confidence"]["error_code"] == "medium"
    assert any("local OCR read 'U4'" in w for w in v["warnings"])


def test_sevenseg_decoder_exact_and_abstains():
    from scripts.vision.dataset import make_flat, make_nameplate
    assert sevenseg.decode(make_flat("E1", 1334))["code"] == "E1"
    assert sevenseg.decode(make_nameplate("CARRIER", "40MAQ0361", 5)) is None
