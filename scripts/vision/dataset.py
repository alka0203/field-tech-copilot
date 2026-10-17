"""Deterministic synthetic evaluation set with known ground truth.

Base images (20):
  * 10 seven-segment error codes, perspective-composited onto a procedural
    "unit front panel" background using scripts/synth/composite_onto_photos.py
  * 4 flat augmented seven-segment panels (no background)
  * 6 nameplate-like text cards (PIL) with a model string
Plus 4 "rusted" nameplates whose ground truth is *empty* (honesty test, eval
case #14 in CONTEXT.md).

Degradations applied to every base image: blur_mild, blur_heavy, dark, glare,
rot15, rot90. Nothing is written to disk unless `save_fixtures` is called.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "synth"))

import augment as _augment  # noqa: E402
from augment import augment_panel as _augment_panel  # noqa: E402
from composite_onto_photos import warp_panel_onto_background  # noqa: E402
from seven_segment import render_seven_segment  # noqa: E402

def augment_panel(img, seed):
    """augment.augment_panel plus a re-seed of the albumentations pipeline (which
    ignores random/np.random seeds) so the eval set is bit-reproducible."""
    try:
        _augment._PIPELINE.set_random_seed(seed)
    except Exception:  # noqa: BLE001
        pass
    return _augment_panel(img, seed=seed)


DISPLAY_CODES = ["E1", "U4", "P8", "F28", "L3", "H6", "E7", "P1", "H3", "F14"]
FLAT_CODES = ["E1", "U4", "F28", "H6"]
NAMEPLATES = [
    # (brand text on plate, model string, brand, family)
    ("MITSUBISHI ELECTRIC", "MXZ-4C36NA", "mitsubishi", "MXZ"),
    ("CARRIER", "40MAQ0361", "carrier", "40MAQ"),
    ("DAIKIN", "FTXS25LVJU", "daikin", "FTXS"),
    ("MITSUBISHI ELECTRIC", "PUZ-A42NKA7", "mitsubishi", "PUZ"),
    ("CARRIER", "38MAQB361", "carrier", "38MAQ"),
    ("MITSUBISHI ELECTRIC", "MSZ-FH12NA", "mitsubishi", "MSZ-FH"),
]
DEGRADATIONS = ["blur_mild", "blur_heavy", "dark", "glare", "rot15", "rot90"]

_FONT_CANDIDATES = ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
                    "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(size: int) -> ImageFont.ImageFont:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default(size)


@dataclass
class Sample:
    id: str
    kind: str                    # display | flat_display | nameplate | rusted
    degradation: str             # clean | blur_mild | ...
    bgr: np.ndarray = field(repr=False)
    truth: dict = field(default_factory=dict)   # {error_code, model, model_family, brand}

    @property
    def base_id(self) -> str:
        return self.id.rsplit("__", 1)[0]


# ---------------------------------------------------------------- base images

def _noise_bg(w: int, h: int, rng: np.random.Generator, base=(170, 172, 175)) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    grad = 0.85 + 0.15 * (xx / w) + 0.1 * (yy / h)
    arr = np.stack([np.full((h, w), c, np.float32) * grad for c in base], -1)
    arr += rng.normal(0, 4, arr.shape).astype(np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def make_display(code: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    W, H = 1280, 960
    bg = _noise_bg(W, H, rng)
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle((300, 250, 980, 650), 30, fill=(205, 207, 210), outline=(120, 120, 125), width=6)  # fascia
    panel = render_seven_segment(code)
    panel = augment_panel(panel, seed=seed)
    aspect = panel.width / panel.height
    qh = 220
    qw = int(qh * aspect)
    cx, cy = W // 2, 450
    j = lambda: int(rng.integers(-10, 11))  # noqa: E731  perspective jitter
    corners = [(cx - qw // 2 + j(), cy - qh // 2 + j()), (cx + qw // 2 + j(), cy - qh // 2 + j()),
               (cx + qw // 2 + j(), cy + qh // 2 + j()), (cx - qw // 2 + j(), cy + qh // 2 + j())]
    out = warp_panel_onto_background(panel, bg, corners)
    return cv2.cvtColor(np.asarray(out), cv2.COLOR_RGB2BGR)


def make_flat(code: str, seed: int) -> np.ndarray:
    # rendered natively at ~4x size (a close-up of the display), not upscaled, so edges are sharp
    panel = augment_panel(render_seven_segment(code, digit_w=240, digit_h=400, gap=48, padding=80), seed=seed)
    return cv2.cvtColor(np.asarray(panel), cv2.COLOR_RGB2BGR)


def make_nameplate(brand_text: str, model: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    W, H = 1100, 760
    img = _noise_bg(W, H, rng, base=(190, 192, 195))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, W - 20, H - 20), outline=(60, 60, 60), width=4)
    ink = (25, 25, 30)
    d.text((60, 50), brand_text, font=_font(56), fill=ink)
    rows = [f"MODEL  {model}", f"SERIAL  {int(rng.integers(10**8, 10**9))}",
            "VOLTS 208-230  PH 1  HZ 60", "REFRIGERANT R410A  FACTORY CHARGE 6.5 LB",
            "MAX FUSE 25 A   MIN CIRCUIT AMPS 18.1"]
    y = 150
    for i, r in enumerate(rows):
        d.text((60, y), r, font=_font(52 if i == 0 else 34), fill=ink)
        y += 105 if i == 0 else 75
    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    # mild sensor noise + very slight blur: a "good phone photo" of a plate
    arr = cv2.GaussianBlur(arr, (0, 0), 0.8)
    return arr


def make_rusted(seed: int) -> np.ndarray:
    """A nameplate that is corroded beyond legibility: faint text under heavy
    multi-scale rust texture. Ground truth: nothing is readable."""
    rng = np.random.default_rng(seed)
    W, H = 1100, 760
    plate = np.zeros((H, W, 3), np.float32)
    plate[:] = (45, 80, 140)  # BGR rust base
    for scale, amp in ((4, 60), (16, 45), (64, 35)):
        n = rng.normal(0, 1, (H // scale + 1, W // scale + 1)).astype(np.float32)
        n = cv2.resize(n, (W, H), interpolation=cv2.INTER_CUBIC)[..., None]
        plate += n * amp * np.array([0.4, 0.6, 1.0], np.float32)
    plate = np.clip(plate, 0, 255).astype(np.uint8)
    pil = Image.fromarray(cv2.cvtColor(plate, cv2.COLOR_BGR2RGB))
    layer = Image.new("RGB", pil.size, (0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle((20, 20, W - 20, H - 20), outline=(255, 255, 255), width=6)   # plate border
    ld.text((60, 200), "MODEL  XXXXXXXX", font=_font(52), fill=(255, 255, 255))
    mask = np.asarray(layer.convert("L")).astype(np.float32) / 255.0 * 0.22   # faint ghost of text
    out = np.asarray(pil).astype(np.float32) * (1 - mask[..., None]) + 90 * mask[..., None]
    out = cv2.GaussianBlur(out, (0, 0), 4)
    out += rng.normal(0, 10, out.shape)
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------- degradations

def degrade(bgr: np.ndarray, kind: str, seed: int = 0) -> np.ndarray:
    h, w = bgr.shape[:2]
    if kind == "blur_mild":
        return cv2.GaussianBlur(bgr, (0, 0), 3.0)
    if kind == "blur_heavy":
        return cv2.GaussianBlur(bgr, (0, 0), 9.0)
    if kind == "dark":
        x = (bgr.astype(np.float32) / 255.0) ** 2.2 * 0.35 * 255
        return np.clip(x, 0, 255).astype(np.uint8)
    if kind == "glare":
        # Specular highlight: soft, blown-out ellipse over the display area.
        rng = np.random.default_rng(seed)
        mask = np.zeros((h, w), np.float32)
        cx, cy = int(w * rng.uniform(0.42, 0.58)), int(h * rng.uniform(0.42, 0.55))
        cv2.ellipse(mask, (cx, cy), (int(w * 0.12), int(h * 0.09)), rng.uniform(-30, 30), 0, 360, 1.0, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), min(h, w) * 0.04)
        out = bgr.astype(np.float32) * (1 - mask[..., None]) + 255 * mask[..., None] * 1.4
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind in ("rot15", "rot90"):
        if kind == "rot90":
            return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 15, 1.0)
        return cv2.warpAffine(bgr, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    raise ValueError(kind)


# ---------------------------------------------------------------- assembly

def build_dataset(seed: int = 1234) -> list[Sample]:
    samples: list[Sample] = []
    bases: list[Sample] = []
    for i, code in enumerate(DISPLAY_CODES):
        bases.append(Sample(f"display_{code}", "display", "clean", make_display(code, seed + i),
                            {"error_code": code, "model": "", "model_family": "", "brand": ""}))
    for i, code in enumerate(FLAT_CODES):
        bases.append(Sample(f"flat_{code}", "flat_display", "clean", make_flat(code, seed + 100 + i),
                            {"error_code": code, "model": "", "model_family": "", "brand": ""}))
    for i, (bt, model, brand, fam) in enumerate(NAMEPLATES):
        bases.append(Sample(f"plate_{model}", "nameplate", "clean", make_nameplate(bt, model, seed + 200 + i),
                            {"error_code": "", "model": model, "model_family": fam, "brand": brand}))
    for b in bases:
        b.id += "__clean"
        samples.append(b)
        for j, dg in enumerate(DEGRADATIONS):
            samples.append(Sample(f"{b.base_id}__{dg}", b.kind, dg, degrade(b.bgr, dg, seed + j), dict(b.truth)))
    for i in range(4):
        samples.append(Sample(f"rusted_{i}__clean", "rusted", "clean", make_rusted(seed + 300 + i),
                              {"error_code": "", "model": "", "model_family": "", "brand": ""}))
    return samples


def save_fixtures(samples: list[Sample], out_dir: Path, ids: list[str], max_side: int = 640) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {s.id: s for s in samples}
    for i in ids:
        s = by_id[i]
        im = s.bgr
        sc = max_side / max(im.shape[:2])
        if sc < 1:
            im = cv2.resize(im, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out_dir / f"{i}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 80])
