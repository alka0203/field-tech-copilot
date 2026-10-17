"""Vision pipeline: preprocess -> (Gemini VLM || local OCR) -> normalize -> cross-validate.

`analyze(data)` returns (vision, extras):
  vision  the contract object returned to the UI under `vision`
  extras  {"raw": <vlm raw dict or {}>, "ocr": {...}, "timing_ms": {...}}
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from . import ocr as ocr_mod
from . import preprocess as pp
from . import sevenseg
from . import vlm as vlm_mod
from .normalize import norm_model_key, normalize_brand, normalize_error_code, split_model

LEVELS = ["low", "medium", "high"]
IMAGE_TYPES = {"nameplate", "error_display", "unit", "other", "unreadable"}


def _lower(c: str) -> str:
    return LEVELS[max(0, LEVELS.index(c) - 1)] if c in LEVELS else "low"


def _raise(c: str) -> str:
    return LEVELS[min(2, LEVELS.index(c) + 1)] if c in LEVELS else "low"


def overall_confidence(vision: dict) -> str:
    """Legacy `vlm_confidence`: weakest confidence among the fields that have a value."""
    vals = [vision["field_confidence"][k] for k in ("brand", "model_family", "error_code") if vision.get(k)]
    if not vals:
        return "low"
    return min(vals, key=LEVELS.index)


def _ocr_safe(bgr):
    """Local reader = classical seven-segment decoder + RapidOCR (each optional).
    Returns (parsed_dict | None, error_message). `error_codes` lists the
    segment-decoder code first (it is exact when it fires, and abstains
    otherwise), then regex hits from OCR."""
    t = time.perf_counter()
    parsed = ocr_mod.parse([])
    parsed.update(rotation=0, scores=[], seg_code="", ocr_codes=[])
    err = ""
    try:
        seg = sevenseg.decode(bgr)
    except Exception:  # noqa: BLE001
        seg = None
    if seg:
        parsed["seg_code"] = seg["code"]
        parsed["error_codes"].append(seg["code"])
    if ocr_mod.available():
        try:
            lines, rot = ocr_mod.read(bgr)
            o = ocr_mod.parse(lines)
            o["rotation"] = rot
            o["scores"] = [round(l.score, 3) for l in lines]
            o["ocr_codes"] = list(o["error_codes"])
            codes = parsed["error_codes"] + [c for c in o["error_codes"] if c not in parsed["error_codes"]]
            o["error_codes"] = codes
            o["seg_code"] = parsed["seg_code"]
            parsed = o
        except Exception as e:  # noqa: BLE001
            err = f"local OCR failed: {e}"
    else:
        err = "local OCR not installed"
    parsed["ms"] = round((time.perf_counter() - t) * 1000)
    if err and not seg:
        return None, err
    return parsed, ""


def _from_ocr_only(ocr: dict, quality_usable: bool) -> dict:
    """Build vision fields from OCR alone (no-quota fallback)."""
    code = ocr["error_codes"][0] if ocr["error_codes"] else ""
    fam = ocr["model_family"]
    brand = ocr["brand"]
    mean = (sum(ocr["scores"]) / len(ocr["scores"])) if ocr["scores"] else 0.0
    base = "medium" if mean >= 0.9 else "low"      # never "high": OCR-only has no second opinion
    if code:
        itype = "error_display"
    elif fam or brand:
        itype = "nameplate"
    elif ocr["n_lines"] == 0 and not quality_usable:
        itype = "unreadable"
    else:
        itype = "other"
    code_conf = base if code else "low"
    changes = list(ocr.get("changes", []))
    if ocr.get("seg_code"):
        # classical decoder fired (it abstains when unsure); OCR agreeing makes it "high"
        code_conf = "high" if ocr["seg_code"] in ocr.get("ocr_codes", []) else "medium"
        if ocr.get("ocr_codes") and ocr["seg_code"] not in ocr["ocr_codes"]:
            changes.append(f"Segment decoder read '{ocr['seg_code']}' but OCR read '{ocr['ocr_codes'][0]}'; using segment decoder.")
    return {
        "image_type": itype, "brand": brand, "model_family": fam, "error_code": code,
        "field_confidence": {"brand": base if brand else "low", "model_family": base if fam else "low",
                             "error_code": code_conf},
        "changes": changes,
    }


def analyze(data: bytes, use_vlm: bool = True, use_ocr: bool = True, enhance: bool = True) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    prep = pp.prepare(data, do_enhance=enhance)
    t_pre = time.perf_counter()
    warnings = list(prep.warnings)
    preprocess = list(prep.preprocess)
    extras: dict = {"raw": {}, "ocr": {}, "timing_ms": {}}

    # ---- run OCR and VLM concurrently
    raw: dict | None = None
    ocr: dict | None = None
    ocr_err = ""
    vlm_err = ""
    do_vlm = use_vlm and vlm_mod.available()
    if use_vlm and not do_vlm:
        vlm_err = "GEMINI_API_KEY not set"
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_ocr = ex.submit(_ocr_safe, prep.bgr) if use_ocr else None
        f_vlm = None
        if do_vlm:
            f_vlm = ex.submit(vlm_mod.extract, pp.to_jpeg_bytes(prep.bgr))
        if f_vlm is not None:
            try:
                t = time.perf_counter()
                raw = f_vlm.result()
                extras["timing_ms"]["vlm"] = round((time.perf_counter() - t) * 1000)
            except vlm_mod.VlmUnavailable as e:
                vlm_err = str(e)
        if f_ocr is not None:
            ocr, ocr_err = f_ocr.result()

    if ocr is not None:
        extras["ocr"] = {k: ocr[k] for k in ("lines", "error_codes", "seg_code", "ocr_codes", "models", "brand", "model_family", "rotation", "scores", "ms")}
        if ocr.get("rotation"):
            preprocess.append(f"ocr_rotated_{ocr['rotation']}")
    elif use_ocr and ocr_err:
        warnings.append(f"Local OCR cross-check unavailable ({ocr_err}).")

    if raw is not None:
        vision = _merge_vlm(raw, ocr, prep.quality["usable"], warnings)
        extras["raw"] = raw
    elif ocr is not None:
        if use_vlm:
            warnings.append(f"Gemini unavailable ({vlm_err}); result is from local OCR only - verify on the unit.")
        else:
            warnings.append("Local OCR only (VLM disabled) - verify on the unit.")
        vision = _from_ocr_only(ocr, prep.quality["usable"])
        for c in vision.pop("changes"):
            warnings.append(c)
    else:
        warnings.append(f"No reader available (Gemini: {vlm_err or 'off'}; OCR: {ocr_err or 'off'}).")
        vision = {"image_type": "unreadable", "brand": "", "model_family": "", "error_code": "",
                  "field_confidence": {"brand": "low", "model_family": "low", "error_code": "low"}}
        extras["unavailable"] = True

    if not prep.quality["usable"]:
        fc = vision["field_confidence"]
        for k in fc:
            if fc[k] == "high":
                fc[k] = "medium"
        warnings.append("Image quality is poor: confidence capped at 'medium'.")

    vision["quality"] = prep.quality
    vision["warnings"] = warnings
    vision["preprocess"] = preprocess
    extras["timing_ms"]["preprocess"] = round((t_pre - t0) * 1000)
    extras["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000)
    # canonical key order for readability
    order = ["brand", "model_family", "error_code", "field_confidence", "image_type", "quality", "warnings", "preprocess"]
    return {k: vision[k] for k in order}, extras


def _merge_vlm(raw: dict, ocr: dict | None, usable: bool, warnings: list[str]) -> dict:
    itype = raw.get("image_type") if raw.get("image_type") in IMAGE_TYPES else "other"
    brand = normalize_brand(raw.get("brand", ""))
    family = (raw.get("model_family") or "").strip().upper()
    code_raw = (raw.get("error_code") or "").strip()
    fc = {k: (raw.get("field_confidence", {}).get(k) if raw.get("field_confidence", {}).get(k) in LEVELS else "low")
          for k in ("brand", "model_family", "error_code")}

    # Enforce the refusal contract even if the model half-complied.
    if itype == "unreadable":
        if brand or family or code_raw:
            warnings.append("VLM marked the image unreadable but returned values; values discarded.")
        brand = family = code_raw = ""
        reason = raw.get("refusal_reason") or "text not legible"
        warnings.append(f"Unreadable image: {reason}")
        fc = {"brand": "low", "model_family": "low", "error_code": "low"}

    # Normalise OCR-style confusions in the error code.
    code, changes = normalize_error_code(code_raw)
    for c in changes:
        warnings.append(f"{c}: '{code_raw}' -> '{code}'")
    if changes:
        fc["error_code"] = _lower(fc["error_code"])
    if code_raw and not code:
        warnings.append(f"Error code '{code_raw}' could not be normalised.")

    # Fill brand from model prefix when the VLM omitted it but read a known model.
    if not brand and family:
        b, _ = split_model(family)
        if b:
            brand = b
            warnings.append(f"brand '{b}' inferred from model prefix '{family}'.")
            fc["brand"] = "medium"

    # ---- cross-validate against local OCR
    if ocr is not None and (ocr["n_lines"] > 0 or ocr["error_codes"]) and itype != "unreadable":
        if code:
            if ocr["error_codes"]:
                if code in ocr["error_codes"]:
                    if fc["error_code"] == "medium":
                        fc["error_code"] = "high"
                else:
                    fc["error_code"] = _lower(fc["error_code"])
                    warnings.append(f"VLM read error code '{code}' but local OCR read '{ocr['error_codes'][0]}' - verify on the display.")
        elif ocr["error_codes"] and itype == "error_display":
            warnings.append(f"VLM found no error code but local OCR saw '{ocr['error_codes'][0]}' - verify on the display.")
        if family and ocr["model_family"]:
            a, b = norm_model_key(family), norm_model_key(ocr["model_family"])
            if a.startswith(b) or b.startswith(a):
                if fc["model_family"] == "medium":
                    fc["model_family"] = "high"
            else:
                fc["model_family"] = _lower(fc["model_family"])
                warnings.append(f"VLM read model family '{family}' but local OCR read '{ocr['model_family']}' - verify on the nameplate.")
        if brand and ocr["brand"] and brand != ocr["brand"]:
            fc["brand"] = _lower(fc["brand"])
            warnings.append(f"VLM read brand '{brand}' but local OCR read '{ocr['brand']}'.")

    # empty field => low confidence, always
    for k, v in (("brand", brand), ("model_family", family), ("error_code", code)):
        if not v:
            fc[k] = "low"
    return {"image_type": itype, "brand": brand, "model_family": family, "error_code": code, "field_confidence": fc}
