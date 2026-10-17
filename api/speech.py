"""Speech endpoints (auto-mounted by api/app.py: module exposes `router`).

  POST /transcribe     multipart `audio`  -> {transcript, language, engine, duration_s}
  POST /query/voice    multipart `audio`  -> {transcript, parsed, result, note}
  GET  /speech/health  -> {engine, model, loaded}

Speech-to-text is local faster-whisper (no Gemini quota use).  The transcript is
UNTRUSTED text: it is parsed by a deterministic rule-based parser
(scripts/speech/parse_spoken.py); brand / model / code are regex- and
whitelist-constrained, and the only free-text value (`question`) is never placed
into an LLM prompt -- it is used solely as an *embedding query* for retrieval
when no error code was spoken.
"""
from __future__ import annotations

import concurrent.futures
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

REPO = Path(__file__).resolve().parent.parent
for _sub in ("scripts/speech", "scripts/infer"):
    _p = str(REPO / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asr  # noqa: E402  (scripts/speech/asr.py)
from parse_spoken import is_hvac_question, parse_spoken  # noqa: E402

router = APIRouter(tags=["speech"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ENGINE_NAME = "faster-whisper"
# generate_answer() retries Gemini 503s with 15/30/60 s sleeps (~100 s worst case).
# A technician on a roof will not wait that long: bound it, then use the direct RAG extract.
LLM_TIMEOUT_S = float(os.environ.get("SPEECH_LLM_TIMEOUT_S", "90"))
_llm_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-llm")

if os.environ.get("SPEECH_PRELOAD") == "1":          # optional warm start (avoids ~1-2 s on 1st request)
    threading.Thread(target=asr.get_model, daemon=True).start()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TranscribeResponse(BaseModel):
    transcript: str
    language: str
    engine: str
    duration_s: float


class ParsedFields(BaseModel):
    brand: str = ""
    model_family: str = ""
    error_code: str = ""
    question: str = ""


class VoiceResult(BaseModel):
    """Same shape as CopilotResponse in api/app.py."""
    brand: str
    model_family: str
    error_code: str
    fault_name: str
    likely_causes: list[str]
    remedy_steps: list[str]
    source_reference: str
    confidence: str
    vlm_confidence: Optional[str] = None
    note: Optional[str] = None


class VoiceResponse(BaseModel):
    transcript: str
    parsed: ParsedFields
    result: Optional[VoiceResult] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_upload(audio: Optional[UploadFile]) -> bytes:
    if audio is None:
        raise HTTPException(status_code=400, detail="Missing multipart field 'audio'.")
    data = audio.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload exceeds the 25 MB limit.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    return data


def _transcribe(data: bytes) -> asr.Transcription:
    try:
        return asr.transcribe_bytes(data)
    except asr.AudioDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:                      # model download/load failure etc.
        raise HTTPException(status_code=503, detail=f"Speech engine unavailable: {e}")


def _copilot():
    """Import the existing copilot module the same way api/app.py does."""
    import copilot
    return copilot


def _as_list(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)] if v else []


def _to_result(answer: dict, brand: str, model: str, code: str, note_extra: str = "") -> VoiceResult:
    note = answer.get("note") or answer.get("_note") or None
    if note_extra:
        note = f"{note_extra} {note}".strip() if note else note_extra
    return VoiceResult(
        brand=str(answer.get("brand", brand) or brand),
        model_family=str(answer.get("model_family", model) or model),
        error_code=str(answer.get("error_code", code) or code),
        fault_name=str(answer.get("fault_name", "") or ""),
        likely_causes=_as_list(answer.get("likely_causes", [])),
        remedy_steps=_as_list(answer.get("remedy_steps", [])),
        source_reference=str(answer.get("source_reference", "") or ""),
        confidence=str(answer.get("confidence", "low") or "low"),
        note=note,
    )


def _retrieve_by_question(cp, question: str, brand: str, model: str) -> list[dict]:
    """Semantic retrieval for a spoken question with no error code.

    The question is used ONLY as embedding input (never formatted into an LLM
    prompt), which is why this does not call cp.retrieve(): that function's
    arguments are interpolated into the answer prompt by generate_answer().
    """
    collection, embedder = cp._get_collection(), cp._get_embedder()
    query = f"Brand: {brand}  Model: {model}  {question}"
    emb = embedder.encode([query])[0].tolist()
    kwargs: dict = dict(query_embeddings=[emb], n_results=cp.TOP_K,
                        include=["documents", "metadatas", "distances"])
    if brand:
        kwargs["where"] = {"brand": brand}
    res = collection.query(**kwargs)
    return [{"text": d, "meta": m, "score": round(1 - dist, 4)}
            for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])]


def _run_copilot(brand: str, model: str, code: str, question: str) -> tuple[Optional[VoiceResult], Optional[str]]:
    """Returns (result, note).  Never raises for ordinary failures: voice UX wants a message."""
    try:
        cp = _copilot()
        if code:
            chunks = cp.retrieve(brand, model, code)
            via = ""
        else:
            if not is_hvac_question(question):
                return None, ("I couldn't tie that to an HVAC fault. Please say the brand and the "
                              "error code, for example 'Daikin error E 7'.")
            chunks = _retrieve_by_question(cp, question, brand, model)
            via = "No error code was heard; answered from a search on the spoken question."
        if not chunks:
            return None, "No relevant context found in the manual index for what was heard."
        try:
            answer = _llm_pool.submit(cp.generate_answer, brand, model, code, chunks).result(
                timeout=LLM_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            answer = cp._rag_fallback(brand, model, code, chunks)
            answer["_note"] = (f"LLM synthesis timed out after {LLM_TIMEOUT_S:.0f}s - "
                               "direct RAG extract")
        except Exception as e:                  # Gemini down / bad JSON / etc.
            answer = cp._rag_fallback(brand, model, code, chunks)
            answer["_note"] = f"LLM synthesis failed ({type(e).__name__}) - direct RAG extract"
        if "error" in answer:
            return None, answer["error"]
        llm_note = str(answer.get("note") or answer.get("_note") or "")
        if not code and "LLM synthesis" in llm_note:
            # Without the LLM, the direct-extract fallback just returns an arbitrary
            # error-table row -- meaningless for a free-form question.
            return None, ("Free-form questions need the AI summarizer, which is unavailable right now "
                          "(no API key or quota used up). Please say the brand and error code instead.")
        res = _to_result(answer, brand, model, code, via)
        if not (res.fault_name or res.likely_causes or res.remedy_steps):
            return None, ("I found manual sections but could not summarise them (the AI summarizer is "
                          "unavailable or timed out, and this brand has no pre-extracted code table). "
                          "Please try again shortly.")
        return res, None
    except SystemExit:                          # copilot._get_collection() sys.exit()s if no index
        return None, "The manual index (data/chroma) is not available on the server."
    except Exception as e:
        return None, f"Lookup failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/speech/health")
def speech_health():
    return {"engine": ENGINE_NAME, "model": asr.MODEL_NAME, "loaded": asr.is_loaded()}


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe(response: Response, audio: Optional[UploadFile] = File(None)):
    """Speech to text.  Accepts webm/opus, ogg, mp4/m4a or wav (<= 25 MB).
    Silence yields an empty transcript (HTTP 200)."""
    data = _read_upload(audio)
    tr = _transcribe(data)
    response.headers["Server-Timing"] = f"asr;dur={tr.elapsed_s * 1000:.0f}"
    return TranscribeResponse(transcript=tr.text, language=tr.language,
                              engine=tr.engine, duration_s=tr.duration_s)


@router.post("/query/voice", response_model=VoiceResponse)
def query_voice(
    response: Response,
    audio: Optional[UploadFile] = File(None),
    brand: str = Form(""),            # optional UI defaults, used only if not spoken
    model_family: str = Form(""),
):
    """Transcribe -> parse spoken brand/model/code -> RAG lookup."""
    t0 = time.perf_counter()
    data = _read_upload(audio)
    tr = _transcribe(data)
    t_asr = time.perf_counter() - t0

    if not tr.text:
        return VoiceResponse(transcript="", parsed=ParsedFields(), result=None,
                             note="I didn't hear any speech. Please try again, closer to the microphone.")

    pq = parse_spoken(tr.text)
    parsed = pq.as_dict()
    # UI-supplied defaults (e.g. a brand picker) fill gaps only; never override speech.
    default_brand = brand.strip().lower()
    if not parsed["brand"] and default_brand in ("carrier", "daikin", "mitsubishi"):
        parsed["brand"] = default_brand
    if not parsed["model_family"]:
        mf = model_family.strip().upper()
        if mf and len(mf) <= 24 and all(c.isalnum() or c == "-" for c in mf):
            parsed["model_family"] = mf
    heard = "; ".join(pq.notes) or None

    b, m, c, q = parsed["brand"], parsed["model_family"], parsed["error_code"], parsed["question"]
    note: Optional[str] = heard
    result: Optional[VoiceResult] = None

    if not (b or m or c or q):
        note = ("I couldn't make out a brand, model or error code. Please say it again, "
                "for example: 'Carrier 40 M A Q, error code E 1'.")
    elif c and not b:
        note = (f"I heard error code {c} but no brand. The same code means different things on "
                "Carrier, Daikin and Mitsubishi - please say the brand too." + (f" ({heard})" if heard else ""))
    elif not c and not q:
        note = (f"I heard {' '.join(x for x in (b, m) if x)} but no error code. "
                "Please say the code, for example 'error E 1'." + (f" ({heard})" if heard else ""))
    else:
        result, lookup_note = _run_copilot(b, m, c, q)
        if lookup_note:
            note = f"{lookup_note} ({heard})" if heard else lookup_note

    response.headers["Server-Timing"] = (
        f"asr;dur={t_asr * 1000:.0f}, total;dur={(time.perf_counter() - t0) * 1000:.0f}")
    return VoiceResponse(transcript=tr.text, parsed=ParsedFields(**parsed), result=result, note=note)
