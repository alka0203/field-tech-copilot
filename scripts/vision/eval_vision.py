"""Vision evaluation on synthetic labeled images.

  .venv/bin/python scripts/vision/eval_vision.py                # local path only, zero API calls
  .venv/bin/python scripts/vision/eval_vision.py --gemini 8     # + Gemini on a fixed <=8-image sample

Local path = preprocess/quality + RapidOCR + regex/normalisation (no network).
Gemini path = full pipeline (schema-constrained VLM + OCR cross-check).

Writes data/eval/vision/results.json and results.md. A local-only re-run keeps
the previously recorded Gemini section. Stops immediately on rate limit.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.vision import dataset as ds_mod  # noqa: E402
from scripts.vision import pipeline, preprocess  # noqa: E402
from scripts.vision import vlm as vlm_mod  # noqa: E402
from scripts.vision.normalize import norm_model_key  # noqa: E402

OUT_DIR = REPO / "data" / "eval" / "vision"
RESULTS = OUT_DIR / "results.json"

# Fixed Gemini sample (8): spans clean/blur/dark/glare/rotation/nameplate/unreadable
GEMINI_SAMPLE = [
    "display_U4__clean", "display_F28__blur_heavy", "display_L3__dark", "display_H6__glare",
    "plate_MXZ-4C36NA__clean", "plate_40MAQ0361__rot15", "display_E7__rot90", "rusted_0__clean",
]

FLAGS = {"blur": "blurry", "dark": "too dark", "over": "over-exposed", "glare": "glare"}


def jpeg(bgr, q=92) -> bytes:
    return cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


def score(sample, vision: dict, extras: dict) -> dict:
    """Per-image correctness. `ok` is the headline metric for that image kind."""
    t = sample.truth
    out = {"kind": sample.kind}
    if sample.kind in ("display", "flat_display"):
        out["ok"] = vision["error_code"] == t["error_code"]
        out["pred"] = vision["error_code"]
        out["truth"] = t["error_code"]
    elif sample.kind == "nameplate":
        fam_ok = norm_model_key(vision["model_family"]) == norm_model_key(t["model_family"])
        models = [norm_model_key(m) for m in extras.get("ocr", {}).get("models", [])]
        raw_model = norm_model_key(extras.get("raw", {}).get("model_number", ""))
        full_ok = norm_model_key(t["model"]) in models or raw_model == norm_model_key(t["model"])
        out.update(ok=fam_ok, family_ok=fam_ok, full_model_ok=full_ok, brand_ok=vision["brand"] == t["brand"],
                   pred=vision["model_family"], truth=t["model_family"])
    else:  # rusted: correct = refuse (all fields empty)
        out["ok"] = not (vision["brand"] or vision["model_family"] or vision["error_code"])
        out["pred"] = f"{vision['brand']}/{vision['model_family']}/{vision['error_code']}"
        out["truth"] = ""
        out["image_type"] = vision["image_type"]
    return out


def quality_flags(q_warnings: list[str]) -> dict:
    low = [w.lower() for w in q_warnings]
    return {k: any(s in w for w in low) for k, s in FLAGS.items()}


def run_local(samples) -> list[dict]:
    rows = []
    for s in samples:
        data = jpeg(s.bgr)
        t = time.perf_counter()
        q = preprocess.assess_bytes(data)
        t_q = (time.perf_counter() - t) * 1000
        vision, extras = pipeline.analyze(data, use_vlm=False)
        rows.append({
            "id": s.id, "kind": s.kind, "degradation": s.degradation,
            **score(s, vision, extras),
            "quality": q["quality"], "usable": q["quality"]["usable"], "flags": quality_flags(q["warnings"]),
            "quality_ms": round(t_q, 1), "total_ms": extras["timing_ms"]["total"],
            "ocr_lines": extras["ocr"].get("lines", [])[:6], "ocr_rotation": extras["ocr"].get("rotation", 0),
            "ocr_code": (extras["ocr"].get("ocr_codes") or [""])[0], "seg_code": extras["ocr"].get("seg_code", ""),
        })
    return rows


def aggregate(rows: list[dict]) -> dict:
    def acc(sub):
        return {"n": len(sub), "correct": sum(r["ok"] for r in sub),
                "accuracy": round(sum(r["ok"] for r in sub) / len(sub), 3) if sub else None}

    out = {"overall_excl_rusted": acc([r for r in rows if r["kind"] != "rusted"]),
           "by_degradation": {}, "by_kind": {}, "by_kind_x_degradation": {}}
    for dg in ["clean"] + ds_mod.DEGRADATIONS:
        out["by_degradation"][dg] = acc([r for r in rows if r["degradation"] == dg and r["kind"] != "rusted"])
    for k in ("display", "flat_display", "nameplate", "rusted"):
        out["by_kind"][k] = acc([r for r in rows if r["kind"] == k])
    for k in ("display", "flat_display", "nameplate"):
        for dg in ["clean"] + ds_mod.DEGRADATIONS:
            out["by_kind_x_degradation"][f"{k}/{dg}"] = acc([r for r in rows if r["kind"] == k and r["degradation"] == dg])
    # ablation on seven-segment images: general OCR alone vs classical decoder alone vs combined
    seg_rows = [r for r in rows if r["kind"] in ("display", "flat_display")]
    abl = {}
    for dg in ["clean"] + ds_mod.DEGRADATIONS + ["ALL"]:
        sub = [r for r in seg_rows if dg == "ALL" or r["degradation"] == dg]
        n = len(sub)
        abl[dg] = {"n": n,
                   "ocr_only_correct": sum(r["ocr_code"] == r["truth"] for r in sub),
                   "ocr_only_wrong": sum(bool(r["ocr_code"]) and r["ocr_code"] != r["truth"] for r in sub),
                   "segdecoder_only_correct": sum(r["seg_code"] == r["truth"] for r in sub),
                   "segdecoder_only_wrong": sum(bool(r["seg_code"]) and r["seg_code"] != r["truth"] for r in sub),
                   "combined_correct": sum(r["ok"] for r in sub)}
    out["seven_segment_ablation"] = abl
    npl = [r for r in rows if r["kind"] == "nameplate"]
    out["nameplate_full_model_exact"] = acc([dict(ok=r["full_model_ok"]) for r in npl])
    out["nameplate_brand_correct"] = acc([dict(ok=r["brand_ok"]) for r in npl])
    return out


def quality_report(rows: list[dict]) -> dict:
    """How well do the local quality metrics detect the degradations we injected?"""
    rep = {"detection_rate_by_degradation": {}, "blur_score_by_degradation": {}, "latency_ms": {}}
    exp = {"blur_mild": "blur", "blur_heavy": "blur", "dark": "dark", "glare": "glare"}
    for dg in ["clean"] + ds_mod.DEGRADATIONS:
        sub = [r for r in rows if r["degradation"] == dg and r["kind"] != "rusted"]
        d = {"n": len(sub), "flagged_unusable": round(sum(not r["usable"] for r in sub) / len(sub), 3),
             **{f"flag_{k}": round(sum(r["flags"][k] for r in sub) / len(sub), 3) for k in FLAGS}}
        if dg in exp:
            d["target_flag"] = exp[dg]
            d["detection_rate"] = d[f"flag_{exp[dg]}"]
        rep["detection_rate_by_degradation"][dg] = d
        bs = [r["quality"]["blur_score"] for r in sub]
        rep["blur_score_by_degradation"][dg] = {"min": round(min(bs), 1), "median": round(st.median(bs), 1), "max": round(max(bs), 1)}
    ql = sorted(r["quality_ms"] for r in rows)
    rep["latency_ms"] = {"quality_median": round(st.median(ql), 1), "quality_p95": round(ql[int(len(ql) * 0.95) - 1], 1),
                         "local_pipeline_median": round(st.median([r["total_ms"] for r in rows]), 1)}
    return rep


def run_gemini(samples_by_id: dict, n: int) -> dict:
    ids = GEMINI_SAMPLE[:n]
    if not vlm_mod.available():
        return {"skipped": "GEMINI_API_KEY not available"}
    res = {"model": vlm_mod.GEMINI_MODEL, "calls_attempted": 0, "rows": [], "stopped": ""}
    for i in ids:
        s = samples_by_id[i]
        data = jpeg(s.bgr)
        res["calls_attempted"] += 1
        t = time.perf_counter()
        vision, extras = pipeline.analyze(data, use_vlm=True)
        dt = round((time.perf_counter() - t) * 1000)
        if "vlm" not in extras["timing_ms"]:   # VLM failed -> fallback path was used
            warn = [w for w in vision["warnings"] if "Gemini" in w]
            res["stopped"] = f"VLM unavailable on {i}: {warn[:1]}"
            res["rows"].append({"id": i, "vlm_failed": True, "detail": warn[:1]})
            break
        r = {"id": i, "kind": s.kind, "degradation": s.degradation, **score(s, vision, extras),
             "vision": {k: vision[k] for k in ("brand", "model_family", "error_code", "field_confidence", "image_type")},
             "raw_error_code": extras["raw"].get("error_code"), "raw_model_number": extras["raw"].get("model_number"),
             "warnings": [w for w in vision["warnings"] if "quality" not in w.lower()][:5],
             "latency_ms": dt, "vlm_ms": extras["timing_ms"]["vlm"]}
        res["rows"].append(r)
    ok_rows = [r for r in res["rows"] if "ok" in r]
    res["n"] = len(ok_rows)
    res["correct"] = sum(r["ok"] for r in ok_rows)
    return res


def markdown(local_rows, agg, qrep, gem) -> str:
    L = ["# Vision evaluation (synthetic, labeled)", "",
         f"{len(local_rows)} images: 20 base (10 composited 7-seg displays, 4 flat 7-seg crops, 6 nameplate cards) x "
         "(clean + 6 degradations) + 4 rusted/unreadable plates. Local path = quality metrics + RapidOCR + regex; zero API calls.", "",
         "## Local path accuracy by degradation (displays: error code exact; nameplates: model family exact)", "",
         "| degradation | n | correct | accuracy |", "|---|---|---|---|"]
    for dg, a in agg["by_degradation"].items():
        L.append(f"| {dg} | {a['n']} | {a['correct']} | {a['accuracy']:.0%} |")
    L += ["", "| image kind | n | correct | accuracy |", "|---|---|---|---|"]
    for k, a in agg["by_kind"].items():
        L.append(f"| {k}{' (correct = refuses)' if k == 'rusted' else ''} | {a['n']} | {a['correct']} | {a['accuracy']:.0%} |")
    L += ["", "## Seven-segment ablation (display + flat_display images; 'wrong' = confident wrong answer, abstain is neither)", "",
          "| degradation | n | OCR only: correct / wrong | segment decoder: correct / wrong | combined correct |", "|---|---|---|---|---|"]
    for dg, a in agg["seven_segment_ablation"].items():
        L.append(f"| {dg} | {a['n']} | {a['ocr_only_correct']} / {a['ocr_only_wrong']} | "
                 f"{a['segdecoder_only_correct']} / {a['segdecoder_only_wrong']} | {a['combined_correct']} |")
    L += ["", f"Nameplate full model-string exact: {agg['nameplate_full_model_exact']['correct']}/{agg['nameplate_full_model_exact']['n']}; "
          f"brand correct: {agg['nameplate_brand_correct']['correct']}/{agg['nameplate_brand_correct']['n']}", "",
          "## Quality-check detection (local, no API)", "",
          "| degradation | n | target flag | detection rate | flagged unusable |", "|---|---|---|---|---|"]
    for dg, d in qrep["detection_rate_by_degradation"].items():
        rate = f"{d['detection_rate']:.0%}" if "detection_rate" in d else "-"
        L.append(f"| {dg} | {d['n']} | {d.get('target_flag', '-')} | {rate} | {d['flagged_unusable']:.0%} |")
    L += ["", f"Latency: quality-only median {qrep['latency_ms']['quality_median']} ms (p95 {qrep['latency_ms']['quality_p95']} ms); "
          f"full local pipeline median {qrep['latency_ms']['local_pipeline_median']} ms.", ""]
    if gem and "rows" in gem:
        L += ["## Gemini path (small sample, same images as local)", "",
              f"model `{gem.get('model')}`; {gem['n']} scored, {gem['correct']} correct. {gem.get('stopped', '')}", "",
              "| image | truth | Gemini | local OCR | image_type | field_confidence | ok |", "|---|---|---|---|---|---|---|"]
        lrow = {r["id"]: r for r in local_rows}
        for r in gem["rows"]:
            if "ok" not in r:
                L.append(f"| {r['id']} | - | VLM failed: {r.get('detail')} | | | | |")
                continue
            lo = lrow.get(r["id"], {})
            L.append(f"| {r['id']} | {r['truth'] or '(refuse)'} | {r['pred'] or '(empty)'} | "
                     f"{lo.get('pred') or '(empty)'}{' ok' if lo.get('ok') else ' X'} | {r['vision']['image_type']} | "
                     f"{r['vision']['field_confidence']} | {'yes' if r['ok'] else 'NO'} |")
    elif gem:
        L += ["## Gemini path", "", str(gem)]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemini", type=int, default=0, help="number of Gemini calls (max 8)")
    ap.add_argument("--fixtures", action="store_true", help="also write a few small jpg fixtures")
    args = ap.parse_args()
    n_g = min(args.gemini, 8)

    samples = ds_mod.build_dataset()
    by_id = {s.id: s for s in samples}
    print(f"built {len(samples)} images", file=sys.stderr)

    rows = run_local(samples)
    agg = aggregate(rows)
    qrep = quality_report(rows)

    prev = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    gem = prev.get("gemini")
    if n_g:
        gem = run_gemini(by_id, n_g)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "n_images": len(samples),
               "local": {"aggregate": agg, "quality": qrep, "rows": rows}, "gemini": gem}
    RESULTS.write_text(json.dumps(results, indent=1))
    (OUT_DIR / "results.md").write_text(markdown(rows, agg, qrep, gem))
    if args.fixtures:
        ds_mod.save_fixtures(samples, OUT_DIR / "fixtures",
                             ["display_E1__clean", "display_U4__blur_heavy", "display_L3__dark",
                              "display_H6__glare", "plate_MXZ-4C36NA__clean", "rusted_0__clean"], max_side=480)
    print((OUT_DIR / "results.md").read_text())


if __name__ == "__main__":
    main()
