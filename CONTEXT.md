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
- [x] Phase 1, Step 2 — 10-15 example use-cases written (2026-09-29). See Section 9.
- [x] Phase 1, Step 3 — Done/good definition + measurable success metric written (2026-09-29). See Section 10.
- [x] Phase 1, Step 4 — Constraints/assumptions doc written (2026-09-29). See Section 11. **Awaiting user review before Phase 2.**
- [x] Phase 2, Step 5 — Hands-on portal exploration run (2026-09-29). See Section 12.
- [x] Phase 2, Step 6 — Data-notes written (2026-09-29). See Section 13. **One open question for user: Carrier model families (see Section 13). Awaiting review before Step 7.**
- [ ] Phase 2, Step 7 — Clean target data model
- [ ] Phase 3, Steps 8-11 — Architecture diagram, tech-choice rationale, riskiest-part identification, failure/safety design
- [ ] Phase 4, Step 12 — Skeleton (**this part is actually already done** — see Section 5 — but was built out of order, before Phase 1-3; revisit once Phase 1-3 are complete to confirm nothing needs to change)
- [ ] Phase 4, Steps 13-18 — Pipeline with self-checks, thin end-to-end slice, eval script + baseline, incremental capability + re-eval, API/UI wrap, deploy + re-eval
- [ ] Phase 5, Steps 19-20 — Handoff doc, retrospective

---

## 9. Phase 1, Step 2 — Example use-cases / eval seed questions

Grounded in `sources.yaml` model families. Labels in brackets are for eval design (not shown to end user).

**Exact / deterministic — answerable precisely if manual data exists:**

1. `[exact]` "What does error code U4 mean on a Mitsubishi MXZ-4C36NA?"
2. `[exact]` "My Daikin FTXS35LVMA remote is showing E7 — what's the fault and how do I clear it?"
3. `[exact]` "Carrier 40MAQ outdoor unit is flashing LED code 31 — what component does that point to?"
4. `[exact]` "What refrigerant does a Daikin RXS18LVJU take and what's the factory charge weight?"
5. `[exact]` "Mitsubishi PUZ-A24NHA7, error P8 — thermistor fault or refrigerant fault?"

**Fuzzy / subjective — require synthesis, not single lookup:**

6. `[fuzzy]` "The Mitsubishi MSZ-GL15NA keeps short-cycling in heat mode, no error codes showing. Where do I start?"
7. `[fuzzy]` "Daikin VRV outdoor unit is gurgling loudly for about 30 seconds after startup, then quiets down — normal or fault?"
8. `[fuzzy]` "Carrier 25HCE is cooling but capacity feels low — no codes, no obvious faults. What's the diagnostic path?"
9. `[fuzzy]` "Is it normal for the outdoor fan on a Mitsubishi MUZ-GL09NAH to stop while the compressor is still running?"

**Edge / mixed — stress-test routing and honest admission of ignorance:**

10. `[edge: ambiguous nameplate + code]` "Nameplate is dirty — could be MSZ-FH09NA or MSZ-GL09NA, can't tell. It's showing error 6607. What should I check?"
11. `[edge: unanswerable — out-of-scope question]` "Daikin FTXS60LVMA — what are the torque specs for the scroll compressor bolts?" (system must say the service manual may not contain this)
12. `[edge: standard remedy failed]` "Mitsubishi MXZ-3C24NAHZ, code P8, I already replaced the thermistor per the manual and it came back two days later. Now what?"
13. `[edge: verify prior diagnosis]` "Carrier 38MAQB is showing code 55, previous tech called it a loose comms wire and left. Is that plausible and what else could cause it?"
14. `[edge: no readable nameplate]` "Took a photo of the outdoor unit but the nameplate is rusted out completely. Can you tell the model from the cabinet shape?" (system must decline — no readable text)
15. `[edge: full two-task pipeline]` "Just snapped a photo of a unit at a new job — need the model confirmed and there's an active fault code on the display. Both in one shot." (exercises nameplate ID + error decode in one request)

---

## 10. Phase 1, Step 3 — "Done" and "good" definition

### Must-haves (the bar for calling this project done)

1. **Nameplate ID works** — given a phone photo of an HVAC nameplate, returns the correct manufacturer and model family. Full model-number precision is nice-to-have; family-level is the bar.
2. **Error-code decode works across all three brands** — given manufacturer + model + error code, returns fault description + likely causes + remedy steps, grounded in the manufacturer's own service manual (not a web guess). All three brand pipelines (Daikin, Mitsubishi, Carrier) must be exercised end-to-end.
3. **Honest on ignorance** — when data is absent or the question is out of scope, the system says so rather than hallucinating. Edge cases #11 and #14 in Section 9 are the specific tests for this.
4. **Eval script runs and records a score** — the 15 use-cases from Step 2 are wired into an actual runnable script; results are written down, not eyeballed.
5. **Handoff doc exists** — a zero-context reader can understand what it is, run it locally, and read the eval results.

### Nice-to-haves (cut if time-pressured)

- Full model-number precision beyond family (e.g. `FTXS35LVMA` vs. just `FTXS`)
- ~~All three brands working end-to-end~~ — **revised to must-have** (see decisions log 2026-09-29)
- Any UI beyond a raw API call
- Latency optimization
- Auth, rate limiting, or uptime guarantees

### Measurable success metrics

| Category | Bar | Stretch |
|---|---|---|
| Exact cases (5 questions) | ≥ 4/5 correct once manual data is ingested | 5/5 |
| Edge cases (6 questions) | ≥ 4/6 handled correctly (right answer OR correct refusal to answer) | 6/6 |
| Fuzzy cases (4 questions) | Qualitative pass: diagnostic path matches what a service manual would recommend | — |

**Definition of "correct" for exact cases:** fault name + at least one correct likely cause, matching the manufacturer's own manual text. A confidently wrong answer that contradicts the manual = failure. A correct refusal ("I don't have data for this model/code") = pass.

---

## 11. Phase 1, Step 4 — Constraints & assumptions

**Audience & purpose**
Portfolio/FDE-interview-prep. No real users, no production SLA. Demo path must work when shown; nothing else requires uptime.

**Where it runs**
- Dev/eval: local Mac.
- Demo: single deployed endpoint (platform TBD in Phase 3) — enough for a live URL, not concurrent load.
- No multi-region, no HA, no on-call.

**Data volume**
- ~3 brands × ~4-5 model families × ~5-20 PDFs per family = est. 60-300 PDFs, 50-200 pages each. Not a big-data problem.
- Images: 25 real phone photos (gold subset) + low hundreds of scraped images via free-first providers.
- Error codes: typically 20-100 unique codes per model family — small enough to fit in a prompt if needed.

**Budget**
- VLM: **Google Gemini Flash** (free tier via AI Studio, `GEMINI_API_KEY`). Replaces Anthropic API for all VLM tasks (`vlm_extract_error_codes.py`, `prelabel_vlm.py`). Free tier is sufficient for a one-off pipeline run; no spend cap needed.
- Paid image search: hard-capped by `--max-queries` in existing scripts. Never run without keys explicitly set.
- Compute: local only, no cloud GPU.

**Legal / licensing**
- Never commit scraped image bytes or manufacturer PDFs — manifests only (url, sha256, license, retrieval_date).
- Carrier: explicit "no redistribution" — manifest + hash only.
- Same policy applied uniformly across all three brands.

**Technical constraints**
- Daikin: JS-heavy portal, requires Playwright/Crawl4AI. Mitsubishi + Carrier: static httpx+BeautifulSoup.
- Mitsubishi newer R-454B docs may be behind sign-in — spider must fail loudly, not silently skip.
- All spiders: robots.txt-checked and rate-limited. Do not bypass either.
- Python only. No new language dependencies without an explicit decision.

**Assumptions (revisit if wrong)**
1. Manufacturer portals in `sources.yaml` are still live and structured as expected. **Unverified** — first thing likely to break when spiders run.
2. Error codes are documented inside the PDFs, not just in online knowledge bases. If not, VLM extraction step needs rethinking.
3. Phone-camera image quality is sufficient for a VLM to read a nameplate under reasonable field conditions. Synthetic augmentation pipeline covers hard cases in training.

---

## 7. Decisions log

(Newest first. Add an entry here after every step — don't batch.)

- **2026-09-29** — Carrier confirmed viable: all three model family PDFs (40MAQ, 38MAQB, 25HCE) are live on shareddocs.com via direct URL. Spider must be rewritten from directory-enumeration to URL-seeded fetching. Confirmed URLs recorded in Section 13.
- **2026-09-29** — Phase 2 Step 6 complete: data-notes written; Carrier open question resolved; all three brands confirmed viable.
- **2026-09-29** — Phase 2 Step 5 complete: live portal probes revealed both Mitsubishi seed URLs are dead, Carrier directory listing returns 403 (but direct file URLs may work), Daikin seed is live but canonical domain changed and crawl4ai is not installed. All three portal assumptions from Step 4 need revision in Step 6.
- **2026-09-29** — Replaced Anthropic API with Google Gemini Flash (free tier) for all VLM tasks. Scripts `vlm_extract_error_codes.py` and `prelabel_vlm.py` will need to be updated to use the Gemini SDK instead of the Anthropic SDK. `GEMINI_API_KEY` replaces `ANTHROPIC_API_KEY`.
- **2026-09-29** — Phase 1 Step 4 complete (pending user review): constraints/assumptions written; key explicit assumption flagged — portal URLs unverified until spiders actually run.
- **2026-09-29** — Revised Step 3 must-have: all three brands (Daikin, Mitsubishi, Carrier) working end-to-end is the bar, not a nice-to-have. User confirmed when asked explicitly.
- **2026-09-29** — Phase 1 Step 3 complete (pending user review): defined must-haves vs. nice-to-haves and three measurable success metrics (exact ≥4/5, edge ≥4/6, fuzzy qualitative). Audience-driven: auth/uptime/UI are explicitly nice-to-have given portfolio context.
- **2026-09-29** — Phase 1 Step 2 complete (pending user review): 15 use-cases written, grounded in `sources.yaml` model families, covering 5 exact, 4 fuzzy, and 6 edge/mixed cases. These become the eval seed set in Phase 4 Step 15.
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

## 12. Phase 2, Step 5 — Portal exploration results (2026-09-29)

Run reproducibly: targeted `curl` HEAD/GET probes + DNS lookups against all seed URLs in `sources.yaml`. No full spider runs yet.

| Portal | Expected | Actual |
|---|---|---|
| Mitsubishi `meus1.mylinkdrive.com` | Folder-style PDF listing | HTTP 000 — connection refused. DNS CNAME resolves to `mylinkdrive.com` but no TCP connection. Portal dead. |
| Mitsubishi `nonul.mylinkdrive.com` | Folder-style PDF listing | DNS: no answer. Subdomain gone entirely. |
| Carrier `shareddocs.com/hvac/docs/1009/Public/04/` | HTML directory listing | HTTP 403 — both bot UA and browser UA. Directory listing disabled site-wide under `/hvac/`. |
| Carrier direct PDF URL (guessed filename) | 403 if blocked | HTTP 404 — individual files are reachable in principle; need correct filenames to enumerate. |
| Carrier `shareddocs.com/robots.txt` | Allow/disallow rules | HTTP 404 — no robots.txt. Python `urllib.robotparser` treats 404 as allow-all, so `robots_allow()` will return True (correct behavior). |
| Daikin `daikinac.com/resource-center/` | JS-rendered page, crawl4ai needed | HTTP 200 — site live. robots.txt `Allow: *`. Old domain — canonical is `daikincomfort.com/resource-center/`. |
| `crawl4ai` (Daikin dependency) | Listed in requirements.txt | Not installed. Daikin spider cannot run until `pip install crawl4ai && crawl4ai-setup`. |
| `requirements.txt` | Gemini SDK | Still lists `anthropic>=0.34`. Needs `google-generativeai`. |

**Step 4 assumption check:**
- Assumption 1 (portals live + structured as expected): **FALSE** for Mitsubishi (dead), **PARTIAL** for Carrier (live but no directory listing), **TRUE** for Daikin.
- Assumption 2 (error codes in PDFs): unverifiable — no PDFs collected yet.
- Assumption 3 (phone photo quality sufficient for VLM): unverifiable — no VLM wired in yet.

---

## 13. Phase 2, Step 6 — Data-notes (observations → decisions)

| Observation | Decision |
|---|---|
| Mitsubishi mylinkdrive.com: both subdomains dead (connection refused / DNS gone) | Rewrite `spider_mitsubishi.py` to use `mitsubishicomfort.com/products/sitemap.xml` as product index, then crawl MSZ/MXZ/MUZ/PUZ product pages for PDF links via crawl4ai. |
| Mitsubishi resources page has 1 static PDF ref in raw HTML — rest is JS-rendered | crawl4ai required for Mitsubishi, same as Daikin. Static httpx spider will miss nearly all PDFs. |
| Carrier `shareddocs.com/hvac/` tree: 403 on all directory paths, both bot UA and browser UA | Directory enumeration dead. Spider must use URL-seeded approach instead. |
| Carrier PDFs use hex subdirs (`/00/`, `/08/`, `/0D/`) — not guessable, but accessible once URL is known | Confirmed via web search + HEAD: all three model families have live PDFs. Seed the spider from known URLs. **Resolved — no model family change needed.** |
| Confirmed live Carrier PDF URLs (verified 200 OK): `Public/00/40MAQ-01SM.pdf` (2.2MB), `Public/08/38MAQ-01SM.pdf` (7.7MB), `Public/0D/25HBC-HCE-03SI.pdf` (1.1MB), `Public/03/24-25-9SM.pdf` (6.2MB service manual) | Hard-code these seeds into `spider_carrier.py`. Replace directory-listing logic with direct URL fetch + manifest write. |
| Daikin `daikinac.com/resource-center/` is live, robots.txt `Allow: *`; canonical domain shifted to `daikincomfort.com` | Update spider seed URL from `daikinac.com` to `daikincomfort.com`. No other change needed. |
| `crawl4ai` listed in requirements.txt but not installed | Run `pip install crawl4ai && crawl4ai-setup` before any spider runs. Add to README. |
| `requirements.txt` still lists `anthropic>=0.34` | Replace with `google-generativeai` (Gemini decision from Step 4). Update `vlm_extract_error_codes.py` and `prelabel_vlm.py`. |

---

## 8. Next action

**Phase 2, Step 6 data-notes written (Section 13) — awaiting user review.**

**Carrier resolved** — all three model family PDFs confirmed live on shareddocs.com.
Spider just needs to be rewritten from directory-enumeration to URL-seeded fetching.

Next is **Phase 2, Step 7: clean target data model** — design the
shape of the data we want out of the pipeline (not the shape we were handed).
