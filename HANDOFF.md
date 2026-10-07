# HVAC Field-Tech Copilot — Handoff

A field technician standing in front of an HVAC unit can point their phone at the nameplate or error display and get the fault name, likely causes, and remedy steps — grounded in that manufacturer's own service manual, not a web guess.

**Audience:** Portfolio / FDE-interview-prep piece. Not a production tool.
**Brands covered:** Carrier, Daikin, Mitsubishi Electric
**Model families:** 40MAQ, 38MAQB, 25HCE (Carrier) · FTXS, FTKX, CTX, RMXS (Daikin) · MSZ-FH, MSZ-GE, MXZ, PUZ (Mitsubishi)

---

## Architecture

```
Offline pipeline (run once, baked into the container):
  Spiders (httpx) → PDFs → Docling → Markdown → extract_error_codes_from_md
                                    → build_index.py → ChromaDB (2362 chunks)

Online path (per request):
  Photo → Gemini Flash VLM → brand/model/code
                                     ↓
                         retrieve() — brand-filtered semantic search
                              + exact error_table boost (score=1.0)
                                     ↓
                         generate_answer() — Gemini synthesis over top-5 chunks
                                     ↓
                              JSON response
```

Two chunk types in ChromaDB:
- **error_table** (34 Carrier records) — one chunk per structured error code; gets exact-match boosted when a code is provided
- **troubleshooting** (2328 prose chunks, all 3 brands) — sliding-window extracts from manual text; used for fuzzy/no-code queries and LLM synthesis context

---

## How to run locally

**Prerequisites:** Python 3.12+, `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com)

```bash
git clone git@github.com:alka0203/field-tech-copilot.git
cd field-tech-copilot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# The ChromaDB index is in data/chroma/ (gitignored, built from source)
# If missing, rebuild it:
python scripts/rag/build_index.py --reset

export GEMINI_API_KEY=your_key_here

# Text override mode (no image needed):
python scripts/infer/copilot.py --brand carrier --model 40MAQ --code E1

# API server:
uvicorn api.app:app --reload
# → POST http://localhost:8000/query
# → POST http://localhost:8000/query/image
# → GET  http://localhost:8000/docs   (interactive Swagger UI)
```

---

## API

### `POST /query`
```json
{"brand": "carrier", "model_family": "40MAQ", "error_code": "E1"}
```
```json
{
  "brand": "carrier",
  "model_family": "40MAQ",
  "error_code": "E1",
  "fault_name": "Indoor / outdoor units communication error",
  "likely_causes": ["Wiring mistake", "Indoor or outdoor PCB faulty"],
  "remedy_steps": ["Check wiring between indoor and outdoor units", "..."],
  "source_reference": "38MAQ-01SM",
  "confidence": "high"
}
```

### `POST /query/image`
Multipart form upload of a JPEG/PNG photo. Runs Gemini VLM to extract brand/model/code, then same RAG path. Requires `GEMINI_API_KEY`.

### `GET /health`
Returns `{"status": "ok"}`.

---

## Eval results

Eval script: `scripts/eval/eval_rag.py` — 15 seed use-cases from Phase 1.

| Mode | Exact (≥4/5) | Edge (≥4/6) | Fuzzy |
|------|-------------|-------------|-------|
| RAG-only (no Gemini) | 1/5 | 4/6 | 4 review |
| With Gemini synthesis | 5/5* | 6/6* | 4 review |

\* Gemini synthesis score is from a partially clean run (free-tier quota of 20 req/day means not all 15 cases got LLM synthesis in a single run). Individual case results are consistent: all 5 exact cases pass when Gemini responds; case 11 (torque spec refusal) and case 12 (Mitsubishi P8 with prior repair context) pass only with LLM synthesis.

**Why RAG-only exact score is 1/5 and edge is 4/6:** Only Carrier has structured `error_table` chunks (exact-match boosted). Mitsubishi and Daikin codes exist in prose troubleshooting chunks — LLM synthesis is required to extract a structured answer from that prose. The brand filter (added in Step 16) also prevents cross-brand chunk leakage, so Mitsubishi/Daikin cases correctly return empty when Gemini is unavailable rather than returning a plausible-looking Carrier answer.

**Why RAG-only exact score is 1/5:** Only Carrier has structured `error_table` chunks (Mitsubishi/Daikin use different table formats that weren't parsed by the extractor). The prose content for Mitsubishi/Daikin codes exists in the index — it just requires LLM synthesis to extract a structured answer from it. A brand filter also prevents cross-brand chunk contamination (see Known Limitations #2).

Re-run the eval:
```bash
export GEMINI_API_KEY=...
python scripts/eval/eval_rag.py
# Results written to data/eval/eval_results.jsonl
```

---

## Data pipeline (offline, already run)

13 service manuals indexed (manifests-only committed — no PDFs in the repo):

```
data/manifests/manuals_manifest.csv   # 13 rows: url, sha256, brand, model_family
data/raw/manuals/                      # gitignored: actual PDFs
data/raw/docling/                      # gitignored: Markdown extracts
data/chroma/                           # gitignored: ChromaDB index
```

To re-collect from scratch:
```bash
python scripts/manuals/spider_carrier.py
python scripts/manuals/spider_mitsubishi.py
python scripts/manuals/spider_daikin.py
python scripts/extract/run_docling.py        # ~2-3h on CPU for 13 PDFs
# Note: PUZ-A12-42NKA7 manual causes Docling to hang — extracted via PyMuPDF fallback
python scripts/rag/build_index.py --reset
```

---

## Known limitations

1. **Gemini free tier (20 req/day, occasional 503s)** — the LLM synthesis path is rate-limited. The fallback (RAG direct extract) works for Carrier but returns empty for Mitsubishi/Daikin since those brands have no structured error_table chunks. Upgrading to a paid tier removes this constraint.

2. **Only Carrier has error_table chunks** — `extract_error_codes_from_md.py` parses Carrier's specific table format (DISPLAY column + AMBER LED FLASH CODE). Daikin and Mitsubishi use different layouts. The codes exist in prose chunks and are answerable via LLM synthesis, but not via the fast exact-match boost path.

3. **Outdoor unit manuals are what matter for system error codes** — Mitsubishi U4 and P8 are documented in outdoor unit manuals (MXZ, PUZ), not indoor unit manuals (MSZ-FH, MSZ-GE). The spider was initially collecting the wrong manuals. MXZ and PUZ manuals are now indexed.

4. **PUZ manual extracted via PyMuPDF fallback** — Docling hung on the PUZ-A12-42NKA7 PDF (likely a complex circuit figure). The text-only PyMuPDF extraction is used instead — no figure extraction, but the error code text is intact.

5. **No image eval** — the VLM nameplate extraction path is code-complete but was never tested end-to-end on real phone photos (Gemini free tier quota exhausted during pipeline development). The `data/synth/` directory contains synthetic augmented nameplate images for testing.

---

## Deploy to Fly.io

```bash
# First time:
fly launch --no-deploy
fly secrets set GEMINI_API_KEY=your_key_here

# Every deploy:
fly deploy
```

The `data/chroma/` index is baked into the Docker image at build time (255MB). The image pre-downloads the sentence-transformers model. Cold start is ~10s.

---

## Next steps (if continuing)

- **Extract Daikin/Mitsubishi error_table chunks** — extend `extract_error_codes_from_md.py` to handle their table formats; would give Mitsubishi/Daikin the same fast exact-match boost Carrier gets, and improve RAG-only fallback
- **Test VLM nameplate extraction** on real phone photos
- **Re-run eval** once Gemini quota resets for a clean 15-case synthesis score
- **Red-team**: the `scripts/redteam/` directory has prompt-injection sticker and PDF poisoning scripts that were not run

---

## Retrospective (Step 20)

### What surprised me

**The brand-filter bug took the longest to spot.** The original RAG-only eval showed 5/5 exact — which looked great — but was completely wrong. Carrier `error_table` chunks (e.g. "Overload current protection") were dominating Mitsubishi P8 queries via semantic similarity (~0.52 cosine). The auto-scorer marked those PASS because the response had non-empty fault names. Gemini correctly refused because the context was the wrong brand, and that refusal was what revealed the bug. Lesson: always sanity-check *what* the retriever is returning, not just whether the final answer looks plausible.

**One PDF can block the whole pipeline for days.** The PUZ-A24NHA7 manual caused Docling to hang for 766 CPU-minutes (three-plus days). A single complex figure in table detection was enough to stall the entire Mitsubishi eval. PyMuPDF text-only extraction took under one second and produced perfectly usable content. The lesson: always have a fast fallback extractor; don't bet the pipeline on one tool for every input.

**The free-tier quota constraint is more binding than it looks.** 20 Gemini requests/day sounds fine for a 15-case eval, but each 503 retry (15s → 30s → 60s backoff) counts as a request. A run with three 503s consumes a third of the daily budget before producing any answers. This made it impossible to get a clean 15/15 synthesis run. In a real deployment, this would be a blocker on day one.

### What I'd do differently

1. **Write a quota-aware rate-limiter before running any eval.** Track request counts to the LLM API with a local counter; abort cleanly when 80% of quota is consumed rather than burning retries.

2. **Test Docling on a sample page from each PDF before committing to full extraction.** A 5-page sample would have surfaced the PUZ hang in minutes rather than days.

3. **Extract Mitsubishi and Daikin `error_table` chunks from the start.** The RAG-only fallback path is essentially useless for those brands without structured chunks. Treating the LLM synthesis layer as mandatory makes the architecture fragile — any quota or API outage leaves Mitsubishi/Daikin users with empty answers.

4. **Seed the eval with at least one image-mode case.** The VLM extraction path (`POST /query/image`) is code-complete but was never tested end-to-end on a real photo. For a "phone points at nameplate" product, that's the primary user journey — it should have been in the eval from day one.

### What went well

- The fde-build-methodology's "understand before design" approach paid off: discovering that outdoor unit manuals (MXZ, PUZ) hold the system fault codes — not indoor unit manuals (MSZ) — would have been an expensive mistake to find post-deployment.
- The sliding-window chunking with brand+source metadata made the brand-filter fix a one-line change rather than a re-index.
- Keeping the offline pipeline (spiders → Docling → ChromaDB) fully separate from the online path meant the index could be rebuilt without touching the API.
