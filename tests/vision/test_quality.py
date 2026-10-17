import cv2
import numpy as np

from scripts.vision import preprocess as pp


def _q(arr, make_jpeg):
    return pp.assess_bytes(make_jpeg(arr))


def test_sharp_image_is_usable(sharp_arr, make_jpeg):
    r = _q(sharp_arr, make_jpeg)
    assert r["quality"]["usable"] and r["warnings"] == []
    assert r["quality"]["width"] == 800 and r["quality"]["height"] == 600


def test_blur_lowers_score_and_warns(sharp_arr, make_jpeg):
    sharp = _q(sharp_arr, make_jpeg)["quality"]["blur_score"]
    blurred = cv2.GaussianBlur(sharp_arr, (0, 0), 8)
    r = _q(blurred, make_jpeg)
    assert r["quality"]["blur_score"] < sharp / 10
    assert not r["quality"]["usable"]
    assert any("blurry" in w for w in r["warnings"])


def test_dark_image_warns(sharp_arr, make_jpeg):
    r = _q((sharp_arr * 0.1).astype(np.uint8), make_jpeg)
    assert any("too dark" in w for w in r["warnings"]) and not r["quality"]["usable"]


def test_glare_fraction_measured(sharp_arr, make_jpeg):
    a = sharp_arr.copy()
    a[:200, :400] = 255  # 1/6 of the frame blown out
    q = _q(a, make_jpeg)["quality"]
    assert 0.15 < q["glare_fraction"] < 0.19


def test_tiny_image_unusable(make_jpeg):
    arr = np.random.default_rng(1).integers(0, 255, (100, 100, 3), dtype=np.uint8)
    assert not _q(arr, make_jpeg)["quality"]["usable"]


def test_exif_orientation_applied(sharp_arr, make_jpeg):
    data = make_jpeg(sharp_arr, exif_orientation=6)   # 90 deg: reported size swaps
    prep = pp.prepare(data)
    assert any("exif_orientation_fixed" in s for s in prep.preprocess)
    assert (prep.quality["width"], prep.quality["height"]) == (600, 800)


def test_large_image_downscaled(make_jpeg):
    arr = np.random.default_rng(2).integers(0, 255, (2400, 3200, 3), dtype=np.uint8)
    prep = pp.prepare(make_jpeg(arr))
    assert max(prep.bgr.shape[:2]) <= pp.MAX_SIDE
    assert any(s.startswith("downscaled") for s in prep.preprocess)
    assert prep.quality["width"] == 3200   # original size reported


def test_clahe_only_for_flat_images(make_jpeg):
    flat = np.full((600, 800, 3), 120, np.uint8)
    flat[::2] += 5
    assert any("clahe" in s for s in pp.prepare(make_jpeg(flat)).preprocess)
    rng = np.random.default_rng(3)
    contrasty = (rng.random((600, 800, 3)) * 255).astype(np.uint8)
    assert not any("clahe" in s for s in pp.prepare(make_jpeg(contrasty)).preprocess)


def test_undecodable_bytes_raise():
    import pytest
    with pytest.raises(ValueError):
        pp.assess_bytes(b"not an image")
