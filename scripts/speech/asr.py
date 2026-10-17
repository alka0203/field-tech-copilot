"""Local speech-to-text engine (faster-whisper / CTranslate2, int8, CPU).

No network at inference time (the model is downloaded once from the HF hub on
first use and cached).  Lazy singleton, thread-safe.

Env overrides:
  SPEECH_MODEL        faster-whisper model name or path   (default: small.en)
  SPEECH_COMPUTE      compute type                         (default: int8)
  SPEECH_THREADS      CPU threads                          (default: min(8, cpu_count))
  SPEECH_PROMPT       "0" disables the domain initial_prompt
"""
from __future__ import annotations

import io
import os
import re
import threading
import time
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
MIN_SECONDS = 0.25

MODEL_NAME = os.environ.get("SPEECH_MODEL", "small.en")
COMPUTE_TYPE = os.environ.get("SPEECH_COMPUTE", "int8")

# Vocabulary bias.  Deliberately contains NO example error codes: a prompt like
# "...E1, U4" makes Whisper hallucinate those codes on noisy/quiet audio.
DOMAIN_PROMPT = (
    "HVAC service call. Brands: Carrier, Daikin, Mitsubishi Electric. "
    "Models: 40MAQ, 38MAQB, 25HCE, FTXS, FTKX, CTX, RMXS, MSZ-FH, MSZ-GE, MXZ, PUZ. "
    "Error code, fault code, thermistor, compressor, inverter, outdoor unit."
)

# Strings Whisper emits on silence / noise (training-data artefacts)
_HALLUCINATIONS = {
    "you", "thank you", "thanks", "thanks for watching", "thank you for watching",
    "bye", "bye bye", "okay", "ok", "so", "uh", "um", "hmm", "mm", "yeah",
    "subtitles by the amara.org community", "[blank_audio]", "(silence)",
}


class AudioDecodeError(ValueError):
    """Raised when the upload is empty, too short, or not decodable audio."""


@dataclass
class Transcription:
    text: str
    language: str
    duration_s: float
    engine: str
    elapsed_s: float


_model = None
_model_lock = threading.Lock()
_infer_lock = threading.Lock()   # one decode at a time keeps CPU/latency predictable


def _threads() -> int:
    env = os.environ.get("SPEECH_THREADS")
    if env:
        return int(env)
    return min(8, os.cpu_count() or 4)


def is_loaded() -> bool:
    return _model is not None


def get_model(name: str | None = None, local_only: bool = False):
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    name or MODEL_NAME, device="cpu", compute_type=COMPUTE_TYPE,
                    cpu_threads=_threads(), local_files_only=local_only,
                )
    return _model


def decode(data: bytes) -> np.ndarray:
    """Decode webm/opus, ogg, mp4/m4a, wav, ... to mono float32 @ 16 kHz."""
    if not data:
        raise AudioDecodeError("Empty audio upload.")
    # Own PyAV decode: faster-whisper 1.2.1's decode_audio passes `metadata_errors=`
    # to av.open(), which PyAV >= 17 rejects (TypeError), so we do not depend on it.
    import av

    try:
        chunks: list[np.ndarray] = []
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise ValueError("no audio stream")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):          # flush
                chunks.append(out.to_ndarray().reshape(-1))
        audio = (np.concatenate(chunks).astype(np.float32) / 32768.0
                 if chunks else np.zeros(0, dtype=np.float32))
    except Exception as e:  # av.error.* (InvalidDataError, ...) / ValueError
        raise AudioDecodeError(
            "Could not decode the audio (supported: webm/opus, ogg, mp4/m4a, wav)."
        ) from e
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size < int(MIN_SECONDS * SAMPLE_RATE):
        raise AudioDecodeError("Audio is empty or too short (< 0.25 s).")
    return audio


def _prepare(audio: np.ndarray) -> np.ndarray:
    """Remove DC offset and peak-normalise quiet recordings (phone mic gain varies)."""
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio)))
    if 1e-4 < peak < 0.5:
        audio = audio * (0.7 / peak)
    return audio


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower().strip(" .,!?[]()") in _HALLUCINATIONS:
        return ""
    return text


def transcribe_array(audio: np.ndarray, prompt: bool | None = None,
                     model_name: str | None = None) -> Transcription:
    t0 = time.perf_counter()
    model = get_model(model_name)
    use_prompt = (os.environ.get("SPEECH_PROMPT", "1") != "0") if prompt is None else prompt
    with _infer_lock:
        segments, info = model.transcribe(
            _prepare(audio),
            language="en",
            beam_size=5,
            initial_prompt=DOMAIN_PROMPT if use_prompt else None,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 300},
            no_speech_threshold=0.6,
            word_timestamps=False,
        )
        parts = []
        for s in segments:               # generator: decoding happens here
            if s.no_speech_prob > 0.8 and s.avg_logprob < -1.0:
                continue                 # likely noise hallucination
            parts.append(s.text)
    text = _clean(" ".join(parts))
    model_tag = (model_name or MODEL_NAME)
    return Transcription(
        text=text,
        language=info.language or "en",
        duration_s=round(len(audio) / SAMPLE_RATE, 2),
        engine=f"faster-whisper/{model_tag}-{COMPUTE_TYPE}",
        elapsed_s=round(time.perf_counter() - t0, 3),
    )


def transcribe_bytes(data: bytes) -> Transcription:
    return transcribe_array(decode(data))
