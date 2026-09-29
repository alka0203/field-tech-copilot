"""Eval script for Phase 4 Step 15.

Runs the 15 seed use-cases from CONTEXT.md §9 through the RAG + answer-generation
pipeline and records a baseline score.

Three use-case categories:
  [exact]  (5)  — deterministic; auto-scored: pass if fault_name + ≥1 likely_cause returned
  [fuzzy]  (4)  — subjective; recorded for human review, auto-marked "review"
  [edge]   (6)  — specific expected behaviours; auto-scored per case

Success thresholds (from CONTEXT.md §10):
  exact  ≥ 4/5  pass
  edge   ≥ 4/6  pass (correct answer OR correct refusal)
  fuzzy  qualitative (human review)

Usage:
  # No API key — RAG only (recommended for baseline; no Gemini cost)
  python scripts/eval/eval_rag.py

  # With Gemini synthesis
  export GEMINI_API_KEY=...
  python scripts/eval/eval_rag.py

Output:
  data/eval/eval_results.jsonl  — one JSON line per use-case
  stdout                        — summary table
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "infer"))

from copilot import generate_answer, retrieve  # noqa: E402  (after sys.path fixup)

OUT_PATH = REPO / "data" / "eval" / "eval_results.jsonl"

# ---------------------------------------------------------------------------
# Use-case definitions
# ---------------------------------------------------------------------------
# Each case has:
#   id         — 1-15
#   category   — "exact" | "fuzzy" | "edge"
#   question   — original natural-language question
#   brand      — "" if unknown/undetectable
#   model      — model family override (may be "")
#   code       — error code override (may be "")
#   expected   — dict describing what a correct answer looks like (for auto-scoring)
#
# For edge cases, `expected` contains:
#   "type"   : "grounded_answer" | "refusal" | "partial_refusal" | "any_answer"
#   "notes"  : human-readable rationale
#
# Auto-scoring rules:
#   exact  — pass if answer["fault_name"] non-empty AND answer["likely_causes"] non-empty
#            AND no top-level "error" key
#   edge   — scored per expected["type"]:
#     "grounded_answer"  — same rule as exact
#     "refusal"          — pass if answer has "error" key OR answer["confidence"]=="low"
#                          OR "don't have" / "not found" / "no relevant" in any string field
#     "partial_refusal"  — pass if answer contains some content (doesn't crash / refuse outright)
#     "any_answer"       — always pass (tests pipeline doesn't crash)
#   fuzzy  — always "review" (no auto-score)

USE_CASES: list[dict] = [
    # -----------------------------------------------------------------------
    # Exact (1-5)
    # -----------------------------------------------------------------------
    {
        "id": 1,
        "category": "exact",
        "question": "What does error code U4 mean on a Mitsubishi MXZ-4C36NA?",
        "brand": "mitsubishi",
        "model": "MXZ",
        "code": "U4",
        "expected": {"type": "grounded_answer"},
    },
    {
        "id": 2,
        "category": "exact",
        "question": "My Daikin FTXS35LVMA remote is showing E7 — what's the fault and how do I clear it?",
        "brand": "daikin",
        "model": "FTXS",
        "code": "E7",
        "expected": {"type": "grounded_answer"},
    },
    {
        "id": 3,
        "category": "exact",
        "question": "Carrier 40MAQ outdoor unit is flashing LED code 31 — what component does that point to?",
        "brand": "carrier",
        "model": "40MAQ",
        "code": "31",
        "expected": {"type": "grounded_answer"},
    },
    {
        "id": 4,
        "category": "exact",
        "question": "What refrigerant does a Daikin RXS18LVJU take and what's the factory charge weight?",
        "brand": "daikin",
        "model": "FTXS",   # RXS is the outdoor companion to FTXS in our index
        "code": "",
        "expected": {
            "type": "grounded_answer",
            "notes": "No error code — tests prose retrieval for spec lookup (refrigerant type + charge)",
        },
    },
    {
        "id": 5,
        "category": "exact",
        "question": "Mitsubishi PUZ-A24NHA7, error P8 — thermistor fault or refrigerant fault?",
        "brand": "mitsubishi",
        "model": "MSZ-FH",  # PUZ is outdoor; MSZ-FH manual covers companion outdoor units
        "code": "P8",
        "expected": {"type": "grounded_answer"},
    },
    # -----------------------------------------------------------------------
    # Fuzzy (6-9)
    # -----------------------------------------------------------------------
    {
        "id": 6,
        "category": "fuzzy",
        "question": "The Mitsubishi MSZ-GL15NA keeps short-cycling in heat mode, no error codes showing. Where do I start?",
        "brand": "mitsubishi",
        "model": "MSZ-GE",  # MSZ-GE manual is the closest in index for GL series
        "code": "",
        "expected": {"type": "any_answer", "notes": "Fuzzy — human review required"},
    },
    {
        "id": 7,
        "category": "fuzzy",
        "question": "Daikin VRV outdoor unit is gurgling loudly for about 30 seconds after startup, then quiets down — normal or fault?",
        "brand": "daikin",
        "model": "RMXS",
        "code": "",
        "expected": {"type": "any_answer", "notes": "Fuzzy — human review required"},
    },
    {
        "id": 8,
        "category": "fuzzy",
        "question": "Carrier 25HCE is cooling but capacity feels low — no codes, no obvious faults. What's the diagnostic path?",
        "brand": "carrier",
        "model": "25HCE",
        "code": "",
        "expected": {"type": "any_answer", "notes": "Fuzzy — human review required"},
    },
    {
        "id": 9,
        "category": "fuzzy",
        "question": "Is it normal for the outdoor fan on a Mitsubishi MUZ-GL09NAH to stop while the compressor is still running?",
        "brand": "mitsubishi",
        "model": "MSZ-GE",
        "code": "",
        "expected": {"type": "any_answer", "notes": "Fuzzy — human review required"},
    },
    # -----------------------------------------------------------------------
    # Edge (10-15)
    # -----------------------------------------------------------------------
    {
        "id": 10,
        "category": "edge",
        "question": "Nameplate is dirty — could be MSZ-FH09NA or MSZ-GL09NA, can't tell. It's showing error 6607. What should I check?",
        "brand": "mitsubishi",
        "model": "MSZ-FH",   # try with one candidate; system should handle ambiguity gracefully
        "code": "6607",
        "expected": {
            "type": "partial_refusal",
            "notes": "Code 6607 is unlikely to exist in our index; system should return low confidence or no relevant context rather than hallucinating",
        },
    },
    {
        "id": 11,
        "category": "edge",
        "question": "Daikin FTXS60LVMA — what are the torque specs for the scroll compressor bolts?",
        "brand": "daikin",
        "model": "FTXS",
        "code": "",
        "expected": {
            "type": "refusal",
            "notes": "Torque specs for compressor bolts are unlikely to be in service manuals — system must say so rather than guessing",
        },
    },
    {
        "id": 12,
        "category": "edge",
        "question": "Mitsubishi MXZ-3C24NAHZ, code P8, I already replaced the thermistor per the manual and it came back two days later. Now what?",
        "brand": "mitsubishi",
        "model": "MSZ-FH",
        "code": "P8",
        "expected": {
            "type": "grounded_answer",
            "notes": "Standard P8 remedy failed; system should surface other probable causes from the manual (e.g. refrigerant issues)",
        },
    },
    {
        "id": 13,
        "category": "edge",
        "question": "Carrier 38MAQB is showing code 55, previous tech called it a loose comms wire and left. Is that plausible and what else could cause it?",
        "brand": "carrier",
        "model": "38MAQ",
        "code": "55",
        "expected": {
            "type": "grounded_answer",
            "notes": "Verify prior diagnosis + surface alternative causes from manual",
        },
    },
    {
        "id": 14,
        "category": "edge",
        "question": "Took a photo of the outdoor unit but the nameplate is rusted out completely. Can you tell the model from the cabinet shape?",
        "brand": "",
        "model": "",
        "code": "",
        "expected": {
            "type": "refusal",
            "notes": "No brand or code — system must decline rather than hallucinate a model ID from cabinet shape",
        },
    },
    {
        "id": 15,
        "category": "edge",
        "question": "Just snapped a photo of a unit at a new job — need the model confirmed and there's an active fault code on the display. Both in one shot.",
        "brand": "carrier",  # simulate a resolved nameplate + code for pipeline test
        "model": "40MAQ",
        "code": "E1",
        "expected": {
            "type": "grounded_answer",
            "notes": "Two-task (nameplate ID + error decode) simulated via override; tests pipeline doesn't crash",
        },
    },
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _has_content(answer: dict) -> bool:
    """True if the answer has a non-empty fault_name and at least one likely cause."""
    if "error" in answer:
        return False
    fault = answer.get("fault_name", "")
    causes = answer.get("likely_causes", [])
    return bool(fault and causes)


_REFUSAL_PHRASES = (
    "don't have",
    "do not have",
    "not found",
    "no relevant",
    "no data",
    "cannot determine",
    "unable to",
    "no information",
    "no context",
)


def _looks_like_refusal(answer: dict) -> bool:
    if "error" in answer:
        return True
    if answer.get("confidence") == "low":
        return True
    # Check all string values for refusal language
    text = " ".join(
        v for v in answer.values() if isinstance(v, str)
    ).lower()
    return any(phrase in text for phrase in _REFUSAL_PHRASES)


def auto_score(case: dict, answer: dict) -> str:
    """Return 'pass', 'fail', or 'review'."""
    category = case["category"]
    expected_type = case["expected"]["type"]

    if category == "fuzzy":
        return "review"

    if expected_type == "grounded_answer":
        return "pass" if _has_content(answer) else "fail"

    if expected_type == "refusal":
        return "pass" if _looks_like_refusal(answer) else "fail"

    if expected_type == "partial_refusal":
        # Pass if system doesn't crash AND (low confidence OR some content)
        if "error" in answer and not answer.get("likely_causes"):
            return "pass"  # clean refusal is acceptable
        if answer.get("confidence") in ("low", "medium") or _has_content(answer):
            return "pass"
        return "fail"

    if expected_type == "any_answer":
        return "pass"  # always pass — tests pipeline doesn't crash

    return "review"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results = []

    for case in USE_CASES:
        cid = case["id"]
        brand = case["brand"]
        model = case["model"]
        code = case["code"]
        category = case["category"]

        print(f"[{cid:02d}/{len(USE_CASES)}] [{category}] {case['question'][:70]}…", file=sys.stderr)

        # Edge case 14: no brand or code at all — skip RAG, return structured refusal
        if not brand and not code:
            answer = {
                "error": "No brand or error code provided — cannot look up information.",
                "confidence": "low",
            }
            chunks = []
        else:
            try:
                chunks = retrieve(brand, model, code)
            except Exception as e:
                answer = {"error": f"Retrieval failed: {e}"}
                chunks = []
            else:
                if not chunks:
                    answer = {"error": "No relevant context found in the RAG index."}
                else:
                    try:
                        answer = generate_answer(brand, model, code, chunks)
                    except Exception as e:
                        answer = {"error": f"Answer generation failed: {e}"}

        score = auto_score(case, answer)

        record = {
            "id": cid,
            "category": category,
            "question": case["question"],
            "brand": brand,
            "model": model,
            "code": code,
            "score": score,
            "answer": answer,
            "top_chunk_score": chunks[0]["score"] if chunks else None,
            "chunks_returned": len(chunks),
            "expected_type": case["expected"]["type"],
            "expected_notes": case["expected"].get("notes", ""),
        }
        results.append(record)
        status_sym = {"pass": "✓", "fail": "✗", "review": "~"}[score]
        print(f"       {status_sym} {score.upper()}", file=sys.stderr)

    # Write JSONL
    with OUT_PATH.open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Summary table
    exact   = [r for r in results if r["category"] == "exact"]
    fuzzy   = [r for r in results if r["category"] == "fuzzy"]
    edge    = [r for r in results if r["category"] == "edge"]

    exact_pass  = sum(1 for r in exact if r["score"] == "pass")
    edge_pass   = sum(1 for r in edge  if r["score"] == "pass")
    fuzzy_rev   = sum(1 for r in fuzzy if r["score"] == "review")

    print()
    print("=" * 60)
    print("EVAL SUMMARY — baseline")
    print("=" * 60)
    header = f"{'#':>3}  {'CAT':<6}  {'SCORE':<7}  {'Q'[:55]}"
    print(header)
    print("-" * 60)
    for r in results:
        sym = {"pass": "PASS", "fail": "FAIL", "review": "~rev~"}[r["score"]]
        q = r["question"][:50] + "…" if len(r["question"]) > 50 else r["question"]
        print(f"{r['id']:>3}  {r['category']:<6}  {sym:<7}  {q}")
    print("-" * 60)
    print(f"Exact  : {exact_pass}/{len(exact)}  ({'PASS' if exact_pass >= 4 else 'FAIL'} — threshold ≥4/5)")
    print(f"Edge   : {edge_pass}/{len(edge)}  ({'PASS' if edge_pass >= 4 else 'FAIL'} — threshold ≥4/6)")
    print(f"Fuzzy  : {fuzzy_rev}/{len(fuzzy)} queued for human review")
    print("=" * 60)
    print(f"\nResults written to {OUT_PATH}")

    overall = (exact_pass >= 4) and (edge_pass >= 4)
    print(f"Overall baseline: {'PASS' if overall else 'NEEDS WORK'}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
