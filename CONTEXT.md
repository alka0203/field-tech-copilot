# field-tech-copilot — Context

**Read this file first, before anything else, in any new session — including
a fresh chat window, a different machine, or a different person picking this
up.** It is written to be self-contained: everything needed to continue this
build is below, without needing to read prior chat history or already know
the methodology being followed.

---

## 1. What this project is

A field technician standing in front of an HVAC unit today has to manually
search a paper or PDF service manual (or the open web) to identify a model
from its nameplate and decode a blinking/LCD error code — slow, and
error-prone under time pressure in the field. This copilot lets them point a
phone camera at the nameplate or error display and get the model identified
plus the error code explained (likely causes + remedy steps), grounded in
that manufacturer's own manual rather than a guess.

**Real audience: portfolio / FDE-interview-prep piece**, not a live
production tool for real technicians (confirmed with user, 2026-09-29). This
matters because it sets what's a must-have vs. nice-to-have for the rest of
the build: a clean eval + a handoff writeup + demonstrated engineering
judgment matter more than auth, uptime, or scale. The *demo path* still needs
to actually work when shown, but there's no real user base to protect from
downtime.

**Vertical / scope:** HVAC, three brands chosen for having crawlable manual
portals with explicit error-code documentation: **Daikin, Mitsubishi
Electric, Carrier**. (Solar — SMA/SolarEdge/Growatt — was considered and
rejected in favor of HVAC; see decisions log.)

---

## 2. The methodology being followed

This build follows a 5-phase, 20-step methodology (Claude Code's
"fde-build-methodology" skill — invoke that skill by name in a Claude Code
session to get the full original text; the condensed version below is enough
to continue without it). Core principle: **understand before you design,
design before you build, build the thinnest working version before you build
anything well.**

### Phase 1 — Understand the problem (before any code)
1. Problem statement, 1-2 sentences: who's stuck, what they do manually today, what this replaces.
2. 10-15 real example questions/use-cases a real user would actually type, grounded in real data (not invented), mixing exact/deterministic, fuzzy/subjective, and edge/mixed cases. **This list becomes the eval set later — it's the single most valuable Phase 1 artifact.**
3. Define "done" and "good": must-haves vs. nice-to-haves, plus at least one *measurable* success metric.
4. Write down constraints/assumptions explicitly: data volume, where it runs, budget, privacy, real audience.

### Phase 2 — Look at the real data/materials (before designing)
5. Explore hands-on and reproducibly (executed notebook or captured script output, not a forgotten REPL session). Sanity-check anything that "seems obvious" before trusting it.
6. Write data-notes: every observation paired with the decision it leads to (not just "this field is messy" — "this field is unreliable, therefore we exclude it and rely on Y instead").
7. Design the clean target data model based on the shape you want, not the shape you were handed.

### Phase 3 — System design
8. An actual diagram (boxes/arrows), not just prose.
9. Each component's tech choice + written "why," including alternatives rejected.
10. Identify the riskiest/least-certain parts of the design and say explicitly those get tested first.
11. Think through failure/safety up front; prefer structural enforcement over a prompt-level promise wherever it's cheap; verify guardrails actually hold.

### Phase 4 — Build in thin slices
12. Skeleton first: repo, folders, secrets handling (.env + .env.example), committed dependency manifest.
13. Data/ingestion pipeline first, with self-checks baked in against the Phase 2 notes' concrete numbers.
14. ONE ugly-but-working end-to-end path first, proving the riskiest idea (Step 10) works at all.
15. Turn the Step 2 example questions into an actual eval script now; run it; record the baseline score.
16. Add remaining capability one piece at a time, re-running the eval after each addition.
17. Wrap it: API, then UI, only once core logic is validated.
18. Deploy, then re-run the same eval against the deployed version.

### Phase 5 — Hand off
19. Handoff doc for a zero-context reader: problem statement, architecture diagram, how to run it, eval results, known limitations, next steps.
20. Short retrospective: what surprised you, what you'd do differently.

### Cross-cutting practices (applied throughout every phase, not a separate step)
- Keep this context file current **after every step**, not batched.
- If working step-by-step, actually stop and wait for review between steps — don't bundle several into one message.
- Commit per step, with the *reasoning* in the commit message, not just what changed.
- Correct errors transparently — name what was wrong and why, don't quietly patch.
- Independent audit pass (fresh reviewer, re-derive from primary sources) before calling anything guardrail-related "done."
- Prefer structural enforcement (typed enums, restricted views/roles, schema constraints) over relying on convention or a prompt asking nicely.

---

## 3. Working agreement for this project

- **Pacing: step-by-step with review.** Confirmed with user 2026-09-29. Do ONE step, present it, and stop — wait for explicit go-ahead before starting the next step. Do not bundle multiple steps into one message.
- Update this file (status, decisions log, next action) after every single step, before stopping.
- Commit + push after every step, with the reasoning in the commit message.

---

## 4. Deviation from methodology order (flagged, per the methodology's own rule)

The Phase 4 skeleton (repo, folder structure, all scripts, dependency
manifest, `sources.yaml`) was built **before** any Phase 1 understanding work
happened, because it was driven by a pasted research brief that already
specified the tools/APIs/architecture in detail. That brief functionally
substituted for Phase 1-3, but nothing was written down in this project's own
words — no problem statement, no use-cases grounded in real data, no
explicit done/good bar, no constraints doc.

We are now going back and doing Phase 1 properly, retroactively, treating the
existing skeleton as an **unvalidated draft** until it's actually exercised:
nothing in `scripts/` has been run against a live manufacturer portal or a
paid API yet (except the synthetic-data pipeline, which was smoke-tested and
works — see inventory below). Do not treat any script's existence as proof it
works end-to-end against real inputs until Phase 4 Steps 13-15 happen.

---

## 5. Repo inventory (what exists, and its actual proof status)

Repo: `git@github.com:alka0203/field-tech-copilot.git` (private).

| Path | What it is | Proof status |
|---|---|---|
| `sources.yaml` | Brands (Daikin, Mitsubishi, Carrier), model families, image query templates — single source of truth | Design only, not exercised |
| `scripts/manuals/spider_carrier.py`, `spider_mitsubishi.py` | Static httpx+BeautifulSoup spiders, robots.txt-checked, rate-limited | **Never run** against the live site |
| `scripts/manuals/spider_daikin.py` | Crawl4AI (Playwright) crawler for Daikin's JS-heavy portal | **Never run** |
| `scripts/images/fetch_openverse.py`, `fetch_wikimedia.py` | Free image search, no API key needed | **Never run** |
| `scripts/images/fetch_brave.py`, `fetch_serpapi.py` | Paid image search, refuse to run without `BRAVE_API_KEY`/`SERPAPI_API_KEY`, hard-capped by `--max-queries` | **Never run** (no keys set) |
| `scripts/images/run_img2dataset.py` | Downloads `images_manifest.csv` into `data/raw/images/` | **Never run** (no manifest yet) |
| `scripts/extract/run_docling.py`, `find_error_pages.py`, `vlm_extract_error_codes.py` | PDF → Markdown/tables/figures → keyword-located error pages → VLM schema extraction (needs `ANTHROPIC_API_KEY`) | **Never run** (no manuals collected yet) |
| `scripts/dedupe/dedupe_pipeline.py` | sha256 → phash → CLIP relevance/dedupe → resolution filter | **Never run** (no raw images yet) |
| `scripts/synth/seven_segment.py`, `augment.py`, `composite_onto_photos.py` | From-scratch 7-segment/LCD renderer, backlight/blur/glare/JPEG augmentation, homography compositor onto a real photo's screen region | **Smoke-tested end-to-end and confirmed working** — rendered "E1", augmented it, warped it onto a mock photo, visually verified the perspective and legibility were correct. This is the one piece of the pipeline actually proven to work. |
| `scripts/redteam/sticker_images.py` | PyRIT `AddImageTextConverter` prompt-injection stickers, own images only | Not run (needs `pip install pyrit`) |
| `scripts/redteam/poison_pdf.py` | Hidden-text (white-on-white / tiny-font) injection into a copy of a collected manual | Not run (needs a real manual first) |
| `scripts/redteam/poisoned_notes.py` | Plain-text prompt-injection work-order note cases | **Run and confirmed working** — generates `data/manifests/redteam_notes.jsonl`, no external deps |
| `scripts/labeling/label_config.xml`, `prelabel_vlm.py` | Label Studio project config + VLM pre-labeling (needs `ANTHROPIC_API_KEY`) | Not run |

**Bottom line:** nothing that touches live manufacturer sites or paid APIs
has been exercised. No manuals, no scraped images, no error-code table, and
no eval set exist yet. The only proven components are the synthetic-image
pipeline and the poisoned-notes generator, both of which need no external
data or paid API.

---

## 6. Phase progress checklist

- [x] Phase 1, Step 1 — Problem statement written and confirmed by user (2026-09-29). See Section 1 above.
- [ ] Phase 1, Step 2 — 10-15 example use-cases (**next action, see Section 8**)
- [ ] Phase 1, Step 3 — Done/good definition + measurable success metric
- [ ] Phase 1, Step 4 — Constraints/assumptions doc
- [ ] Phase 2, Steps 5-7 — Hands-on data exploration, data-notes, clean data model
- [ ] Phase 3, Steps 8-11 — Architecture diagram, tech-choice rationale, riskiest-part identification, failure/safety design
- [ ] Phase 4, Step 12 — Skeleton (**this part is actually already done** — see Section 5 — but was built out of order, before Phase 1-3; revisit once Phase 1-3 are complete to confirm nothing needs to change)
- [ ] Phase 4, Steps 13-18 — Pipeline with self-checks, thin end-to-end slice, eval script + baseline, incremental capability + re-eval, API/UI wrap, deploy + re-eval
- [ ] Phase 5, Steps 19-20 — Handoff doc, retrospective

---

## 7. Decisions log

(Newest first. Add an entry here after every step — don't batch.)

- **2026-09-29** — Rewrote this file to be fully self-contained (methodology primer inlined, full repo inventory with proof status, explicit checklist) so a fresh session/window with zero chat history can pick this up without re-deriving anything. Prompted by user request.
- **2026-09-29** — Confirmed audience is portfolio/FDE-interview-prep, not a real production tool. Shifts done/good (Step 3, still pending) toward eval quality + writeup over auth/scale/uptime.
- **2026-09-29** — Locked Phase 1 Step 1 problem statement (nameplate ID + error-code decode from a phone photo, grounded in the manufacturer's own manual) as drafted, confirmed by user without edits.
- **2026-09-29** — Created this context file; chose step-by-step-with-review pacing at user's request (over autonomous-with-flagged-decisions).
- **2026-09-27** — Pushed initial skeleton to GitHub as private repo `alka0203/field-tech-copilot`.
- **2026-09-27** — Chose HVAC vertical (Daikin/Mitsubishi/Carrier) over solar (SMA/SolarEdge/Growatt) — both were viable per the research brief; HVAC picked by user preference when scaffolding started.
- **2026-09-27** — Chose to scaffold in a new sibling directory (`/Users/asanthos/Documents/field-tech-copilot`) rather than inside the unrelated `recipe-vault` repo, per user choice.
- **2026-09-27** — Manifests-only licensing model adopted throughout: never commit scraped image bytes or manufacturer PDFs, only `data/manifests/*.csv` (url, sha256, license, retrieval date) plus the generator scripts. Driven by the research brief's legal-risk analysis (ManualsLib-style terms bans, no redistribution grant on scraped images).
- **2026-09-27** — Paid API scripts (`fetch_brave.py`, `fetch_serpapi.py`, `vlm_extract_error_codes.py`, `prelabel_vlm.py`) all refuse to run without their API key explicitly set in the environment, and the two paid image fetchers are hard-capped by `--max-queries` — so a re-run can't silently burn budget.

---

## 8. Next action

**Phase 1, Step 2: write 10-15 real example use-cases/questions** a
technician would actually type or ask this copilot, grounded in the actual
brands/model families already in `sources.yaml` (Daikin: FTXS/FTKF/RXS/VRV/
Skyair; Mitsubishi: MSZ/MUZ/MXZ/PUZ; Carrier: 40MAQ/38MAQB/25HCE) — not
invented-sounding generic examples. Mix in:
- Exact/deterministic cases (e.g. "what does error code U4 mean on a
  Mitsubishi MXZ") — answerable precisely if the manual data exists.
- Fuzzy/subjective cases (e.g. "the unit keeps short-cycling, what's likely
  going on") — require synthesis, not lookup.
- 2-3 deliberately mixed/edge cases that stress-test whatever routing the
  design will need later (e.g. a question needing both nameplate ID AND
  error-code lookup at once; a question the manual data can't actually
  answer, to test whether the system admits it doesn't know rather than
  guessing).

Draft this list, present it, and **stop for review** — do not proceed to
Step 3 (done/good definition) without explicit go-ahead, per the working
agreement in Section 3.
