"""Randomizes a rendered error-screen panel before compositing: backlight
color, contrast, blur, glare, JPEG noise. Perspective warp happens separately
in composite_onto_photos.py, against the destination photo's screen region.
"""
from __future__ import annotations

import random

import albumentations as A
import numpy as np
from PIL import Image

BACKLIGHT_TINTS = [
    (255, 60, 60),   # red LED (error state)
    (255, 160, 40),  # amber
    (80, 220, 255),  # blue LCD backlight
    (200, 255, 200), # green LCD backlight
]

_PIPELINE = A.Compose(
    [
        A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.8),
        A.GaussianBlur(blur_limit=(3, 5), p=0.4),
        A.ImageCompression(quality_range=(40, 90), p=0.6),
        A.RandomShadow(shadow_roi=(0, 0, 1, 1), num_shadows_limit=(1, 2), p=0.3),  # glare/reflection proxy
        A.GaussNoise(std_range=(0.02, 0.1), p=0.3),
    ]
)


def retint(img: Image.Image, tint: tuple[int, int, int] | None = None) -> Image.Image:
    """Recolors the bright ('on') pixels toward a random backlight tint,
    keeping near-black pixels dark so the segment shape stays readable."""
    tint = tint or random.choice(BACKLIGHT_TINTS)
    arr = np.asarray(img).astype(np.float32)
    brightness = arr.max(axis=-1, keepdims=True) / 255.0
    tint_arr = np.array(tint, dtype=np.float32)
    out = arr * (1 - brightness) + tint_arr * brightness
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def augment_panel(img: Image.Image, seed: int | None = None) -> Image.Image:
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
    img = retint(img)
    arr = np.asarray(img)
    augmented = _PIPELINE(image=arr)["image"]
    return Image.fromarray(augmented)
