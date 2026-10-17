# Vision evaluation (synthetic, labeled)

144 images: 20 base (10 composited 7-seg displays, 4 flat 7-seg crops, 6 nameplate cards) x (clean + 6 degradations) + 4 rusted/unreadable plates. Local path = quality metrics + RapidOCR + regex; zero API calls.

## Local path accuracy by degradation (displays: error code exact; nameplates: model family exact)

| degradation | n | correct | accuracy |
|---|---|---|---|
| clean | 20 | 18 | 90% |
| blur_mild | 20 | 16 | 80% |
| blur_heavy | 20 | 8 | 40% |
| dark | 20 | 16 | 80% |
| glare | 20 | 8 | 40% |
| rot15 | 20 | 15 | 75% |
| rot90 | 20 | 14 | 70% |

| image kind | n | correct | accuracy |
|---|---|---|---|
| display | 70 | 38 | 54% |
| flat_display | 28 | 21 | 75% |
| nameplate | 42 | 36 | 86% |
| rusted (correct = refuses) | 4 | 4 | 100% |

## Seven-segment ablation (display + flat_display images; 'wrong' = confident wrong answer, abstain is neither)

| degradation | n | OCR only: correct / wrong | segment decoder: correct / wrong | combined correct |
|---|---|---|---|---|
| clean | 14 | 7 / 5 | 8 / 0 | 12 |
| blur_mild | 14 | 5 / 5 | 10 / 0 | 10 |
| blur_heavy | 14 | 3 / 5 | 6 / 0 | 8 |
| dark | 14 | 6 / 5 | 5 / 0 | 10 |
| glare | 14 | 1 / 3 | 1 / 0 | 2 |
| rot15 | 14 | 7 / 2 | 2 / 0 | 9 |
| rot90 | 14 | 2 / 9 | 8 / 0 | 8 |
| ALL | 98 | 31 / 34 | 40 / 0 | 59 |

Nameplate full model-string exact: 36/42; brand correct: 36/42

## Quality-check detection (local, no API)

| degradation | n | target flag | detection rate | flagged unusable |
|---|---|---|---|---|
| clean | 20 | - | - | 5% |
| blur_mild | 20 | blur | 70% | 70% |
| blur_heavy | 20 | blur | 100% | 100% |
| dark | 20 | dark | 100% | 100% |
| glare | 20 | glare | 100% | 5% |
| rot15 | 20 | - | - | 5% |
| rot90 | 20 | - | - | 5% |

Latency: quality-only median 14.1 ms (p95 16.5 ms); full local pipeline median 223.5 ms.

## Gemini path (small sample, same images as local)

model `gemini-3.7-flash`; 0 scored, 0 correct. VLM unavailable on display_U4__clean: ["Gemini unavailable (Gemini unavailable: 504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': 'Deadline expired before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}); result is from local OCR only - verify on the unit."]

| image | truth | Gemini | local OCR | image_type | field_confidence | ok |
|---|---|---|---|---|---|---|
| display_U4__clean | - | VLM failed: ["Gemini unavailable (Gemini unavailable: 504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': 'Deadline expired before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}); result is from local OCR only - verify on the unit."] | | | | |
