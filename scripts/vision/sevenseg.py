"""Tiny classical seven-segment decoder (OpenCV + NumPy, no model, no API).

Why: general-purpose OCR is trained on printed text; on seven-segment
glyphs it confuses U/0, F/E, H/8 (measured in data/eval/vision/results.json).
Seven-segment is a closed alphabet of 2^7 patterns, so we decode it
geometrically:

  1. find the dark display panel (Otsu on V, morphological close, largest
     external contour) -> filled panel mask + its tilt;
  2. threshold lit segments inside the panel (midway between panel
     background and the 99.5th-percentile brightness, so dim 'ghost'
     segments of LCDs are not counted);
  3. de-rotate (tilt estimated from the panel rectangle, 90-degree
     alternatives tried), crop to the lit bounding box, split digits by
     empty column gaps ('1' is narrow so is right-aligned in its cell);
  4. sample the 7 segment regions of each cell and look the on/off pattern
     up in the glyph table from scripts/synth/seven_segment.py.

Limits (be honest): assumes a dark panel with bright segments, roughly
frontal view (perspective of a few degrees; a strong keystone breaks the
fixed segment geometry), no heavy glare over the digits. The decoder
returns None rather than guessing when any cell is not a valid glyph.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "synth"))
from seven_segment import SEGMENTS  # noqa: E402

from .normalize import CODE_RE, normalize_error_code

# char preference when several chars share a segment pattern (0/O, 5/S, F/R, 8/B...)
_PREF = "0123456789EUPFAHLCDTNB-"
GLYPH: dict[tuple, str] = {}
for _ch in _PREF:
    GLYPH.setdefault(tuple(int(x) for x in SEGMENTS[_ch]), _ch)

CELL_ASPECT = 0.6                      # digit_w / digit_h in the renderer
# segment regions as (u0, u1, v0, v1) in cell-relative coordinates
_T = 0.22
_TV = _T * CELL_ASPECT
REGIONS = {
    "a": (0.25, 0.75, 0.0, _TV), "g": (0.25, 0.75, 0.5 - _TV / 2, 0.5 + _TV / 2), "d": (0.25, 0.75, 1 - _TV, 1.0),
    "f": (0.0, _T, 0.12, 0.44), "b": (1 - _T, 1.0, 0.12, 0.44),
    "e": (0.0, _T, 0.56, 0.88), "c": (1 - _T, 1.0, 0.56, 0.88),
}
ON_FRAC = 0.4
LIT_FRAC = 0.3        # lit threshold between panel background and bright segments (ghost segments sit at ~0.2)


def _dark_region(v: np.ndarray, region: np.ndarray | None):
    """Largest closed dark contour (Otsu on V, optionally restricted to `region`)."""
    h, w = v.shape
    if region is None:
        t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        vals = v[region > 0].reshape(-1, 1)
        if vals.size < 200:
            return None
        t, _ = cv2.threshold(vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = (v <= t).astype(np.uint8) * 255
    if region is not None:
        dark &= region
    k = max(5, int(0.04 * min(h, w)))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    cs, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    return c if cv2.contourArea(c) >= 0.02 * h * w else None


def _panel(v: np.ndarray):
    """Return (filled_panel_mask, tilt_deg in [0,45]) or None.

    Two nested Otsu passes: the first finds the dark region (which on a dim
    photo may be the whole fascia), the second searches inside it for the
    darker display panel proper."""
    h, w = v.shape
    c = _dark_region(v, None)
    if c is None:
        return None
    mask = np.zeros_like(v)
    cv2.drawContours(mask, [c], -1, 255, -1)
    c2 = _dark_region(v, mask)
    if c2 is not None and cv2.contourArea(c2) >= 0.1 * cv2.contourArea(c):
        c = c2
        mask = np.zeros_like(v)
        cv2.drawContours(mask, [c], -1, 255, -1)
    (_, _), (rw, rh), ang = cv2.minAreaRect(c)
    ang = ang % 90.0
    return mask, float(min(ang, 90.0 - ang))


def _rotate(img: np.ndarray, deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    if deg % 360 == 0:
        return img
    d = int(np.hypot(h, w)) + 2
    canvas = np.zeros((d, d), img.dtype)
    y0, x0 = (d - h) // 2, (d - w) // 2
    canvas[y0:y0 + h, x0:x0 + w] = img
    M = cv2.getRotationMatrix2D((d / 2, d / 2), deg, 1.0)
    return cv2.warpAffine(canvas, M, (d, d), flags=cv2.INTER_NEAREST)


def _decode_mask(lit: np.ndarray) -> tuple[str, bool] | None:
    ys, xs = np.nonzero(lit)
    if len(xs) < 50:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = lit[y0:y1, x0:x1] > 0
    H, W = m.shape
    if H < 12 or W < 6:
        return None
    cols = m.any(axis=0)
    runs, start = [], None
    for i, c in enumerate(list(cols) + [False]):
        if c and start is None:
            start = i
        elif not c and start is not None:
            runs.append([start, i])
            start = None
    min_gap = max(2, int(0.04 * H))
    merged = [runs[0]]
    for r in runs[1:]:
        if r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    if not (2 <= len(merged) <= 5):          # real codes have >= 2 glyphs; single blobs are usually glare/noise
        return None
    Wd = CELL_ASPECT * H
    out, clean = [], True
    for a, b in merged:
        rw = b - a
        if rw >= 0.75 * Wd:
            ca, cb = a, a + max(rw, 1)
            if rw > 1.3 * Wd:
                return None
        else:
            ca, cb = b - Wd, b                      # narrow glyph ('1'): right-aligned in its cell
        cw = cb - ca
        pat = []
        for s in "abcdefg":
            u0, u1, v0, v1 = REGIONS[s]
            xa, xb = int(round(ca + u0 * cw)), int(round(ca + u1 * cw))
            ya, yb = int(round(v0 * H)), int(round(v1 * H))
            xa, xb = max(xa, 0), min(max(xb, xa + 1), W)
            reg = m[ya:max(yb, ya + 1), xa:xb]
            fr = float(reg.mean()) if reg.size else 0.0
            pat.append(1 if fr > ON_FRAC else 0)
            if 0.3 < fr < 0.5:
                clean = False
        ch = GLYPH.get(tuple(pat))
        if ch is None:
            return None
        out.append(ch)
    return "".join(out), clean


def decode(bgr: np.ndarray) -> dict | None:
    """Try to read a seven-segment error code. Returns {"code", "raw", "clean", "rotation"} or None."""
    h, w = bgr.shape[:2]
    s = 640.0 / max(h, w)
    if s < 1:
        bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    v = bgr.max(axis=2)
    p = _panel(v)
    if p is None:
        return None
    mask, tilt = p
    inside = v[mask > 0]
    if inside.size < 200:
        return None
    hi, bg = float(np.percentile(inside, 99.5)), float(np.median(inside))
    if hi - bg < 25:
        return None
    thr = bg + LIT_FRAC * (hi - bg)
    lit = ((v > thr) & (mask > 0)).astype(np.uint8) * 255
    n, lab, stats, _ = cv2.connectedComponentsWithStats(lit, connectivity=8)
    for i in range(1, n):                              # drop speckle
        if stats[i, cv2.CC_STAT_AREA] < 0.0004 * lit.size:
            lit[lab == i] = 0
    if n - 1 > 40:
        return None                                    # text-heavy image, not a display
    for base in (0, 90, -90):
        for sign in ((1,) if tilt < 0.5 else (1, -1)):
            ang = base + sign * tilt
            r = _decode_mask(_rotate(lit, ang))
            if r is None:
                continue
            raw, clean = r
            if not clean:
                continue          # a segment region was half-lit: ambiguous, abstain rather than guess
            code, _ = normalize_error_code(raw)
            if CODE_RE.match(code):
                return {"code": code, "raw": raw, "clean": clean, "rotation": ang}
    return None
