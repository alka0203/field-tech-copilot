"""Real-model integration test on tiny generated webm/opus fixtures.
Skipped automatically if the faster-whisper model is not cached locally."""
import json
from pathlib import Path

import pytest

import asr
from parse_spoken import parse_spoken

FIX = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIX / "manifest.json").read_text())


@pytest.fixture(scope="module")
def model():
    try:
        return asr.get_model(local_only=True)
    except Exception as e:  # not downloaded / offline
        pytest.skip(f"faster-whisper model not cached: {e}")


@pytest.mark.parametrize("item", MANIFEST, ids=[m["id"] for m in MANIFEST])
def test_webm_roundtrip(model, item):
    data = (FIX / f"{item['id']}.webm").read_bytes()
    tr = asr.transcribe_bytes(data)
    p = parse_spoken(tr.text)
    assert (p.brand, p.model_family, p.error_code) == tuple(item["expected"]), tr.text
    assert 1.0 < tr.duration_s < 10.0


def test_silence_gives_empty_transcript(model):
    import io
    import wave

    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.random.default_rng(0).normal(0, 20, 16000 * 2)).astype("<i2").tobytes())
    assert asr.transcribe_bytes(buf.getvalue()).text == ""
