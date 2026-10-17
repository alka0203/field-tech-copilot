"""Benchmark ASR + parser on clips from make_clips.py.

    python scripts/speech/bench.py CLIP_DIR [--models base.en small.en] [--glob '*.wav']
                                   [--prompt both|on|off] [--verbose]

Reports per config: field accuracy (brand / model / code exact match after
parsing), canonical-token WER (letters+digits runs are joined, so "E one" ==
"E1" == "E 1"), and mean latency.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asr  # noqa: E402
from parse_spoken import _build_items, _find_brand, _segments, _tokenize, parse_spoken  # noqa: E402
from rapidfuzz.distance import Levenshtein  # noqa: E402


def canon(text: str) -> list[str]:
    toks = _tokenize(text)
    _, bi = _find_brand(toks, [])
    items, _ = _build_items(toks, set())      # brand words kept as words here
    out = []
    for seg in _segments(items):
        out.append("".join(c for c, _ in seg[1]).lower() if seg[0] == "run" else seg[1])
    return out


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = canon(ref), canon(hyp)
    return Levenshtein.distance(r, h), max(len(r), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", type=Path)
    ap.add_argument("--models", nargs="+", default=["base.en"])
    ap.add_argument("--glob", default="*.wav")
    ap.add_argument("--prompt", default="both", choices=["both", "on", "off"])
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    manifest = {m["id"]: m for m in json.loads((a.clips / "manifest.json").read_text())}
    files = sorted(a.clips.glob(a.glob))
    prompts = {"both": [True, False], "on": [True], "off": [False]}[a.prompt]
    for model in a.models:
        for pr in prompts:
            asr._model = None
            asr.MODEL_NAME = model
            asr.get_model(model)
            asr.transcribe_array(asr.decode(files[0].read_bytes()), prompt=pr, model_name=model)  # warm
            errs = refs = 0
            hits = {"brand": 0, "model": 0, "code": 0, "all": 0}
            lat = []
            rtf = []
            for f in files:
                cid = f.stem.split("_snr")[0]
                m = manifest[cid]
                data = f.read_bytes()
                tr = asr.transcribe_array(asr.decode(data), prompt=pr, model_name=model)
                p = parse_spoken(tr.text)
                eb, em, ec = m["expected"]
                ok = (p.brand == eb, p.model_family == em, p.error_code == ec)
                for k, o in zip(("brand", "model", "code"), ok):
                    hits[k] += o
                hits["all"] += all(ok)
                e, n = wer(m["text"], tr.text)
                errs += e
                refs += n
                lat.append(tr.elapsed_s)
                rtf.append(tr.elapsed_s / max(tr.duration_s, 0.01))
                if a.verbose:
                    print(f"  {f.name:28s} {tr.elapsed_s:5.2f}s  {tr.text!r}  -> "
                          f"{p.brand}|{p.model_family}|{p.error_code} {'OK' if all(ok) else 'XX'}")
            N = len(files)
            print(f"{model:9s} prompt={'on ' if pr else 'off'} n={N} "
                  f"brand={hits['brand']}/{N} model={hits['model']}/{N} code={hits['code']}/{N} "
                  f"all={hits['all']}/{N} WER={100 * errs / refs:5.1f}% "
                  f"lat mean={statistics.mean(lat):.2f}s p95={sorted(lat)[int(0.95 * (N - 1))]:.2f}s "
                  f"RTF={statistics.mean(rtf):.2f}")


if __name__ == "__main__":
    main()
