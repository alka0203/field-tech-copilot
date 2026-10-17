"""Local (no-API) image preprocessing and quality metrics.

Everything here is OpenCV/NumPy/Pillow only and must stay fast: the
/vision/quality endpoint calls `assess_bytes` and has a <300 ms budget.

Quality metrics (all computed on a bounded-size copy so scores are comparable
between a 12 MP phone photo and a 640 px thumbnail):
  blur_score     variance of the Laplacian on a 640-px-max-side gray image.
                 Low = blurry. Calibrated on synthetic data (see
                 data/eval/vision/results.json -> quality_calibration).
  brightness     mean gray level, 0..255.
  glare_fraction fraction of pixels that are blown out in ALL channels
                 (min(B,G,R) >= 245). Coloured LED segments are not counted,
                 only white-ish specular highlights / over-exposure.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1600          # downscale target for anything sent to the VLM / OCR
BLUR_SIDE = 640          # fixed side for the Laplacian metric
MIN_SIDE_OK = 240        # below this the image is too small to read text

# Thresholds (calibrated, see eval_vision.py --calibrate output)
BLUR_MIN = 60.0          # variance-of-Laplacian below => "blurry"
DARK_MEAN = 40.0         # too dark if p99 < DARK_P99_ABS, or (mean < DARK_MEAN and p99 < DARK_P99)
DARK_P99 = 150.0
DARK_P99_ABS = 120.0
BRIGHT_MEAN = 215.0      # mean gray above => over-exposed
GLARE_WARN = 0.015       # blown-out fraction above => glare warning
GLARE_UNUSABLE = 0.30
LOW_CONTRAST_STD = 28.0  # gray std below => CLAHE


@dataclass
class Prepared:
    bgr: np.ndarray                      # preprocessed image (<= MAX_SIDE), what OCR/VLM see
    quality: dict
    warnings: list[str]
    preprocess: list[str] = field(default_factory=list)


def load_image(data: bytes, max_side: int = MAX_SIDE) -> tuple[np.ndarray, int, int, list[str]]:
    """Decode bytes -> BGR uint8 array with EXIF orientation applied.

    Returns (bgr, orig_width, orig_height, steps_applied). The returned array
    is downscaled to `max_side` if larger. JPEG draft mode lets the decoder
    shrink by 1/2, 1/4, 1/8 during decode, which is the main latency saver.
    """
    steps: list[str] = []
    try:
        img = Image.open(io.BytesIO(data))
        if img.format != "JPEG":
            img.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"not a decodable image: {e}") from e

    orig_w, orig_h = img.size
    try:
        orientation = img.getexif().get(0x0112, 1)
    except Exception:  # noqa: BLE001
        orientation = 1

    if img.format == "JPEG" and max(orig_w, orig_h) > max_side * 1.5:
        img.draft("RGB", (max_side, max_side))
    img = img.convert("RGB")

    if orientation not in (1, None):
        img = ImageOps.exif_transpose(img)
        steps.append(f"exif_orientation_fixed(tag={orientation})")
        if orientation in (5, 6, 7, 8):
            orig_w, orig_h = orig_h, orig_w

    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        arr = cv2.resize(arr, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        steps.append(f"downscaled {orig_w}x{orig_h}->{arr.shape[1]}x{arr.shape[0]}")
    return arr, orig_w, orig_h, steps


def quality_metrics(bgr: np.ndarray, orig_w: int | None = None, orig_h: int | None = None) -> tuple[dict, list[str]]:
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    small = gray
    if max(h, w) > BLUR_SIDE:
        s = BLUR_SIDE / max(h, w)
        small = cv2.resize(gray, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    # Contrast-normalise before the Laplacian so a dim-but-sharp image is not
    # called blurry (variance of Laplacian scales with contrast^2).
    lo, hi = np.percentile(small, (1, 99))
    norm = small
    if hi - lo >= 12:
        norm = np.clip((small.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)
    blur = float(cv2.Laplacian(norm.astype(np.float32), cv2.CV_32F).var())

    brightness = float(gray.mean())
    glare = float((bgr.min(axis=2) >= 245).mean())
    p99 = float(np.percentile(small, 99))
    std = float(small.std())

    q = {
        "blur_score": round(blur, 2),
        "brightness": round(brightness, 2),
        "glare_fraction": round(glare, 4),
        "width": int(orig_w or w),
        "height": int(orig_h or h),
    }
    q["usable"], warns = _judge(q, p99)
    q["_p99"] = p99          # internal; stripped before returning to clients
    q["_std"] = std
    return q, warns


def _judge(q: dict, p99: float) -> tuple[bool, list[str]]:
    warns: list[str] = []
    usable = True
    if min(q["width"], q["height"]) < MIN_SIDE_OK:
        warns.append(f"Image is very small ({q['width']}x{q['height']}) - move closer or use a higher resolution.")
        usable = False
    if q["blur_score"] < BLUR_MIN:
        warns.append("Image looks blurry - hold the phone steady, tap to focus, and retake.")
        usable = False
    if p99 < DARK_P99_ABS or (q["brightness"] < DARK_MEAN and p99 < DARK_P99):
        warns.append("Image is too dark - add light (torch/flash) and retake.")
        usable = False
    elif q["brightness"] > BRIGHT_MEAN:
        warns.append("Image is over-exposed - reduce direct light and retake.")
        usable = False
    if q["glare_fraction"] >= GLARE_UNUSABLE:
        warns.append("Heavy glare covers the image - tilt the phone to avoid reflections and retake.")
        usable = False
    elif q["glare_fraction"] >= GLARE_WARN:
        warns.append("Glare detected - tilt the phone to avoid reflections; the reading may be unreliable.")
    return usable, warns


def enhance(bgr: np.ndarray, q: dict) -> tuple[np.ndarray, list[str]]:
    """Conditional, conservative enhancement. Never applied to well-exposed,
    well-contrasted images."""
    steps: list[str] = []
    out = bgr
    # Gamma lift only for genuinely dark frames.
    if q["brightness"] < 70 and q.get("_p99", 255) < 200:
        gamma = 0.6
        lut = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)], dtype=np.uint8)
        out = cv2.LUT(out, lut)
        steps.append(f"gamma_brighten({gamma})")
    # CLAHE on L channel only for flat images (keeps colour untouched).
    if q.get("_std", 255) < LOW_CONTRAST_STD:
        lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        steps.append("clahe_L(clip=2.0)")
    return out, steps


def prepare(data: bytes, do_enhance: bool = True) -> Prepared:
    bgr, ow, oh, steps = load_image(data)
    q, warns = quality_metrics(bgr, ow, oh)
    if do_enhance:
        bgr, e_steps = enhance(bgr, q)
        steps += e_steps
    q = {k: v for k, v in q.items() if not k.startswith("_")}
    return Prepared(bgr=bgr, quality=q, warnings=warns, preprocess=steps)


def assess_bytes(data: bytes) -> dict:
    """Fast quality-only check for /vision/quality. No enhancement, no OCR."""
    bgr, ow, oh, _ = load_image(data)
    q, warns = quality_metrics(bgr, ow, oh)
    q = {k: v for k, v in q.items() if not k.startswith("_")}
    return {"quality": q, "warnings": warns}


def to_jpeg_bytes(bgr: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()
