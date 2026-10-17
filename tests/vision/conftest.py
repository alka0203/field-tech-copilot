import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _jpeg(arr: np.ndarray, exif_orientation: int | None = None) -> bytes:
    im = Image.fromarray(arr)
    buf = io.BytesIO()
    kw = {}
    if exif_orientation:
        ex = Image.Exif()
        ex[0x0112] = exif_orientation
        kw["exif"] = ex
    im.save(buf, "JPEG", quality=92, **kw)
    return buf.getvalue()


@pytest.fixture(scope="session")
def make_jpeg():
    return _jpeg


@pytest.fixture(scope="session")
def sharp_arr():
    """Textured, well-exposed 800x600 image (checkerboard-ish text-like edges)."""
    rng = np.random.default_rng(0)
    base = (rng.random((60, 80)) > 0.5).astype(np.uint8) * 200 + 25
    return np.repeat(np.repeat(base, 10, 0), 10, 1)[..., None].repeat(3, 2).astype(np.uint8)
