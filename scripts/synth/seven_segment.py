"""Draws 7-segment digits/letters from scratch (no external font dependency).

Segment naming (standard):
   _a_
  f   b
   -g-
  e   c
   _d_

SEGMENTS maps each character to which of (a,b,c,d,e,f,g) are lit, covering
the digits and letters that actually show up in HVAC error codes (E, U, P,
F, A, b, C, d, H, L, n, o, r, t).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

SEGMENTS: dict[str, tuple[bool, ...]] = {
    "0": (1, 1, 1, 1, 1, 1, 0),
    "1": (0, 1, 1, 0, 0, 0, 0),
    "2": (1, 1, 0, 1, 1, 0, 1),
    "3": (1, 1, 1, 1, 0, 0, 1),
    "4": (0, 1, 1, 0, 0, 1, 1),
    "5": (1, 0, 1, 1, 0, 1, 1),
    "6": (1, 0, 1, 1, 1, 1, 1),
    "7": (1, 1, 1, 0, 0, 0, 0),
    "8": (1, 1, 1, 1, 1, 1, 1),
    "9": (1, 1, 1, 1, 0, 1, 1),
    "E": (1, 0, 0, 1, 1, 1, 1),
    "U": (0, 1, 1, 1, 1, 1, 0),
    "P": (1, 1, 0, 0, 1, 1, 1),
    "F": (1, 0, 0, 0, 1, 1, 1),
    "A": (1, 1, 1, 0, 1, 1, 1),
    "B": (0, 0, 1, 1, 1, 1, 1),
    "C": (1, 0, 0, 1, 1, 1, 0),
    "D": (0, 1, 1, 1, 1, 0, 1),
    "H": (0, 1, 1, 0, 1, 1, 1),
    "L": (0, 0, 0, 1, 1, 1, 0),
    "N": (1, 1, 1, 0, 1, 1, 0),  # rendered like a lowercase-n approximation on 7-seg
    "O": (1, 1, 1, 1, 1, 1, 0),
    "R": (1, 0, 0, 0, 1, 1, 1),
    "T": (0, 0, 0, 1, 1, 1, 1),
    "-": (0, 0, 0, 0, 0, 0, 1),
    " ": (0, 0, 0, 0, 0, 0, 0),
}


def _segment_polygons(x0: float, y0: float, w: float, h: float, thick: float) -> dict[str, list[tuple[float, float]]]:
    """Polygon vertices for each of the 7 segments inside box (x0,y0,w,h)."""
    t = thick
    mid_y = y0 + h / 2
    return {
        "a": [(x0 + t, y0), (x0 + w - t, y0), (x0 + w - t / 2, y0 + t / 2), (x0 + t / 2, y0 + t / 2)],
        "b": [(x0 + w - t, y0 + t / 2), (x0 + w, y0 + t), (x0 + w, mid_y - t / 2), (x0 + w - t / 2, mid_y)],
        "c": [(x0 + w - t / 2, mid_y), (x0 + w, mid_y + t / 2), (x0 + w, y0 + h - t), (x0 + w - t, y0 + h - t / 2)],
        "d": [(x0 + t, y0 + h), (x0 + w - t, y0 + h), (x0 + w - t / 2, y0 + h - t / 2), (x0 + t / 2, y0 + h - t / 2)],
        "e": [(x0 + t / 2, mid_y), (x0, mid_y + t / 2), (x0, y0 + h - t), (x0 + t, y0 + h - t / 2)],
        "f": [(x0 + t / 2, y0 + t / 2), (x0, y0 + t), (x0, mid_y - t / 2), (x0 + t / 2, mid_y)],
        "g": [(x0 + t, mid_y - t / 2), (x0 + w - t, mid_y - t / 2), (x0 + w - t / 2, mid_y), (x0 + w - t, mid_y + t / 2), (x0 + t, mid_y + t / 2), (x0 + t / 2, mid_y)],
    }


def render_seven_segment(
    text: str,
    on_color: tuple[int, int, int] = (255, 40, 40),
    off_color: tuple[int, int, int] | None = (40, 10, 10),
    background: tuple[int, int, int] = (10, 10, 10),
    digit_w: int = 60,
    digit_h: int = 100,
    gap: int = 12,
    padding: int = 20,
) -> Image.Image:
    """Renders `text` (upper-cased, spaces allowed) as a 7-segment display panel."""
    text = text.upper()
    n = len(text)
    width = padding * 2 + n * digit_w + (n - 1) * gap
    height = padding * 2 + digit_h
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    thick = digit_w * 0.22

    for i, ch in enumerate(text):
        segs = SEGMENTS.get(ch, SEGMENTS[" "])
        x0 = padding + i * (digit_w + gap)
        y0 = padding
        polys = _segment_polygons(x0, y0, digit_w, digit_h, thick)
        for name, lit in zip("abcdefg", segs):
            color = on_color if lit else off_color
            if color is not None:
                draw.polygon(polys[name], fill=color)
    return img


if __name__ == "__main__":
    render_seven_segment("E1").save("/tmp/e1_preview.png")
    print("wrote /tmp/e1_preview.png")
