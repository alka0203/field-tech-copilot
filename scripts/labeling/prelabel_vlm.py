"""Pre-labels every kept candidate image with a vision LLM, producing Label
Studio "predictions" (pre-annotations) so a human only has to correct them.

Deliberately uses a DIFFERENT model family than whatever ends up serving the
copilot, so eval labels aren't biased toward that model's own blind spots —
per the plan, swap PRELABEL_MODEL if the copilot itself is ever built on
this same model.

Requires: ANTHROPIC_API_KEY. Input: data/manifests/images_kept.csv (from
dedupe_pipeline.py). Output: data/manifests/label_studio_predictions.json
(import this into a Label Studio project using label_config.xml).
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import anthropic
import pandas as pd

KEPT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "images_kept.csv"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "label_studio_predictions.json"
PRELABEL_MODEL = "claude-sonnet-5"

SCHEMA_PROMPT = """Classify this photo for an HVAC field-technician dataset. Return ONLY a JSON
object matching exactly this shape, no other text:

{
  "image_type": "unit" | "nameplate" | "error_display" | "other",
  "legible": true | false,
  "brand": string,        // "" if not legible/visible
  "model_text": string,   // exact text as printed, "" if none visible
  "error_code": string,   // "" if none visible
  "is_relevant": true | false
}"""


def classify(client: anthropic.Anthropic, image_path: Path) -> dict:
    media_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    message = client.messages.create(
        model=PRELABEL_MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": SCHEMA_PROMPT},
                ],
            }
        ],
    )
    return json.loads(message.content[0].text.strip())


def to_ls_prediction(image_path: Path, result: dict) -> dict:
    """Formats one classification as a Label Studio pre-annotation task."""
    return {
        "data": {"image_url": f"file://{image_path}"},
        "predictions": [
            {
                "model_version": PRELABEL_MODEL,
                "result": [
                    {"from_name": "image_type", "to_name": "image", "type": "choices", "value": {"choices": [result["image_type"]]}},
                    {"from_name": "legible", "to_name": "image", "type": "choices", "value": {"choices": ["yes" if result["legible"] else "no"]}},
                    {"from_name": "brand", "to_name": "image", "type": "textarea", "value": {"text": [result.get("brand", "")]}},
                    {"from_name": "model_text", "to_name": "image", "type": "textarea", "value": {"text": [result.get("model_text", "")]}},
                    {"from_name": "error_code", "to_name": "image", "type": "textarea", "value": {"text": [result.get("error_code", "")]}},
                    {"from_name": "is_relevant", "to_name": "image", "type": "choices", "value": {"choices": [str(result["is_relevant"]).lower()]}},
                ],
            }
        ],
    }


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set — refusing to run paid VLM calls.", file=sys.stderr)
        sys.exit(1)
    if not KEPT_PATH.exists():
        print(f"No kept-images manifest at {KEPT_PATH} — run dedupe_pipeline.py first.", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(KEPT_PATH)
    client = anthropic.Anthropic()
    tasks = []
    for path_str in df["path"]:
        image_path = Path(path_str)
        try:
            result = classify(client, image_path)
        except Exception as e:
            print(f"[fail] {image_path}: {e}", file=sys.stderr)
            continue
        tasks.append(to_ls_prediction(image_path, result))
        print(f"[ok] {image_path.name}: {result['image_type']} (relevant={result['is_relevant']})")

    OUT_PATH.write_text(json.dumps(tasks, indent=2))
    print(f"\nWrote {len(tasks)} pre-annotated tasks -> {OUT_PATH}")
    print("Import this into Label Studio (project using label_config.xml) via Import > JSON.")


if __name__ == "__main__":
    main()
