# Eval set schema

Final frozen eval items live as one JSONL row each, exported from Label Studio.
Report metrics **grouped by `source`** — mixing scraped, own-photo, synthetic,
and adversarial items into one aggregate number hides exactly the gap
(real-world nameplates vs. synthetic error screens) this dataset exists to
surface.

```json
{
  "image_id": "sha256 or synth filename stem",
  "source": "web | own | manual_figure | synthetic | adversarial",
  "license": "CC-BY-4.0 | CC0 | all-rights-reserved-manifest-only | ...",
  "image_type": "unit | nameplate | error_display | other",
  "brand": "daikin | mitsubishi | carrier | ...",
  "model": "as printed, empty string if illegible",
  "error_code": "as printed, empty string if none",
  "split": "eval_real | eval_synthetic | eval_adversarial"
}
```

## Target composition (Stage 6)

| Split | Count | Source mix |
|---|---|---|
| `eval_real` | 50-80 | own photos (gold) + web-sourced, hand-verified |
| `eval_synthetic` | ~100 | rendered error screens from `error_codes.jsonl` |
| `eval_adversarial` | 30-50 | sticker images, poisoned PDFs, poisoned notes |

## Error-code rows (`data/manifests/error_codes.jsonl`)

Every row from `vlm_extract_error_codes.py` carries `source_pdf` + `page` —
never drop these when it becomes eval data; they're what makes a disagreement
between the Docling table diff and the VLM extraction reviewable by a human.
