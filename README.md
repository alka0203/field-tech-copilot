# Field-Technician Copilot — Data Pipeline

Data-collection pipeline for an HVAC field-technician copilot: nameplate/unit
photos, error-code displays, and service manuals for Daikin, Mitsubishi
Electric, and Carrier, plus synthetic and adversarial eval data.

Two independent pipelines, tied together by manifests:

- **Manuals** → crawl official portals → Docling extraction → vision-LLM
  error-code extraction, cross-checked against Docling's own tables.
- **Images** → free sources first (Openverse, Wikimedia Commons), paid SERP
  APIs for the long tail (nameplates, error screens) → dedupe/relevance
  filter → synthetic rendering fills the gap web search can't.

## Why this shape

Web image search does not reliably return 50+ correctly labeled HVAC
nameplates and error screens — that content lives on forums, contractor
blogs, and eBay listings, not stock-photo sites. Expect a low keep rate
(often under 30%) from scraped candidates. The gap is filled with:
programmatic 7-segment/LCD rendering composited onto real display photos
(ground truth is free — you chose the code), and 20-30 of your own phone
photos as the "gold" eval subset.

## Legal / licensing (read before running)

- **Never commit scraped image bytes or manufacturer PDFs.** `.gitignore`
  blocks `data/raw/` and loose image/PDF files. Only `data/manifests/*.csv`
  (url, sha256, license, retrieval date) and the generator scripts are
  committed. Anyone reproducing this re-downloads; dead links are an
  accepted cost.
- **CC-licensed images** (Openverse, Wikimedia Commons) may be redistributed
  with attribution — the manifest stores author/license/source per Openverse
  and Wikimedia's own `extmetadata`.
- **Manuals are copyrighted by the manufacturer.** Carrier's shareddocs.com
  PDFs are "Copyright Carrier Corp." with no redistribution grant. Local use
  for RAG/demo purposes is standard practice; bulk redistribution is not.
- **ManualsLib and similar aggregators are never scraped** — their terms
  explicitly ban bots/scrapers/crawlers. They may only be used by a human to
  *discover* model numbers, never automated against.
- **Your own photos and synthetic renders are fully yours** — publish under
  CC BY 4.0.
- Every spider sets a descriptive User-Agent, checks `robots.txt` before
  fetching, and rate-limits to ~1 req/sec on manufacturer sites.
- Not legal advice — see the caveats in the original research brief this
  scaffold implements.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
crawl4ai-setup   # installs Playwright browsers, needed for spider_daikin.py
```

Paid steps require API keys as environment variables — nothing paid runs
without one set explicitly:

| Env var | Used by | Cost |
|---|---|---|
| `BRAVE_API_KEY` | `scripts/images/fetch_brave.py` | $5/1k requests, $5 free credit/mo |
| `SERPAPI_API_KEY` | `scripts/images/fetch_serpapi.py` | free 250/mo, then $25/mo per 1k |
| `ANTHROPIC_API_KEY` | `scripts/extract/vlm_extract_error_codes.py`, `scripts/labeling/prelabel_vlm.py` | per-token |

Both paid image fetchers take `--max-queries` (default 50) as a hard spend cap.

## Pipeline stages

```
Stage 1 — Collect
  scripts/manuals/run_manuals_crawl.py      # Carrier + Mitsubishi (static) + Daikin (JS)
  scripts/images/fetch_openverse.py         # free
  scripts/images/fetch_wikimedia.py         # free
  scripts/images/fetch_brave.py             # paid, capped
  scripts/images/fetch_serpapi.py           # paid, capped
  scripts/images/run_img2dataset.py         # downloads images_manifest.csv -> data/raw/images/
  + 20-30 of your own phone photos -> data/raw/own_photos/

Stage 2 — Dedupe/filter
  scripts/dedupe/dedupe_pipeline.py         # sha256 -> phash -> CLIP -> resolution

Stage 3 — Extract
  scripts/extract/run_docling.py            # Markdown + tables + figure crops per PDF
  scripts/extract/find_error_pages.py       # keyword-locate + render error-code pages
  scripts/extract/vlm_extract_error_codes.py  # schema extraction -> error_codes.jsonl

Stage 4 — Synthesize
  scripts/synth/seven_segment.py            # from-scratch 7-segment/LCD renderer
  scripts/synth/augment.py                  # backlight tint, blur, glare, JPEG noise
  scripts/synth/composite_onto_photos.py    # homography warp onto real display photos

Stage 5 — Red-team
  scripts/redteam/sticker_images.py         # PyRIT AddImageTextConverter on OWN images only
  scripts/redteam/poison_pdf.py             # hidden text in a copy of our own manuals
  scripts/redteam/poisoned_notes.py         # plain-text prompt-injection work-order notes

Stage 6 — Label
  scripts/labeling/prelabel_vlm.py          # VLM pre-labels -> Label Studio predictions
  scripts/labeling/label_config.xml         # Label Studio Community project config
```

`sources.yaml` is the single source of truth for brands, model families, and
image query templates — edit it to add a brand rather than hand-editing
individual scripts.

`eval/schema.md` defines the frozen eval-set row format and target
composition (real / synthetic / adversarial), and why metrics must be
reported separately per `source`.

## Status

Scaffolded, not yet run against live data. `scripts/synth/` (7-segment
rendering + augmentation + compositing) has been smoke-tested end-to-end
locally. Everything that touches a paid API or a live manufacturer portal is
gated behind an explicit env var / cap and has not been executed yet —
run it yourself once you're ready to spend the (small) budget this requires.
