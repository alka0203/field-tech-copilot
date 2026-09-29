# field-tech-copilot — Context

Persistent status file for this project, per the FDE build methodology.
Read this first in any new session before doing anything else.

## Current status

**Phase 1, Step 1 done, Step 2 next** (example use-cases). Working
step-by-step with review — stop after each step and wait for go-ahead.

## Real audience (drives must-have vs. nice-to-have for the rest of the build)

**Portfolio / FDE-interview-prep piece**, not a live production tool for real
technicians. Confirmed with user 2026-09-29. This means: a clean eval +
writeup + demonstrated judgment matter more than auth, uptime, or scale.
Reliability of the *demo path* still matters (it needs to actually work when
shown), but there's no real user base to protect from downtime.

## Phase 1 — Problem statement

A field technician standing in front of an HVAC unit today has to manually
search a paper or PDF service manual (or the open web) to identify a model
from its nameplate and decode a blinking/LCD error code — slow, and
error-prone under time pressure in the field. This copilot lets them point a
phone camera at the nameplate or error display and get the model identified
plus the error code explained (likely causes + remedy steps), grounded in
that manufacturer's own manual rather than a guess.

Confirmed as-is by user, 2026-09-29.

## Deviation from methodology order (flagged per the skill's own instructions)

We built the Phase 4 skeleton (repo, folder structure, scripts, deps,
`sources.yaml`) **before** doing any Phase 1 understanding work, driven by
a pasted research brief that already specified tools/APIs/architecture. That
brief substituted for Phase 1-3 in practice, but nothing was written down in
this project's own words: no problem statement, no example use-cases grounded
in real data, no explicit done/good bar, no constraints/assumptions doc.

We are now going back to do Phase 1 properly, retroactively, before treating
the skeleton as validated. The skeleton itself has NOT been proven against
real data yet — nothing in `scripts/` has been run against live manufacturer
portals or paid APIs. Treat the current code as an unvalidated draft, not a
working system, until Phase 4 Steps 13-15 (pipeline + thin end-to-end slice +
eval) actually happen.

## What exists already (pre-dates this context file)

- `sources.yaml` — brands (Daikin, Mitsubishi, Carrier), model families, image query templates
- `scripts/manuals/` — spiders for Carrier/Mitsubishi (static) + Daikin (Crawl4AI)
- `scripts/images/` — Openverse/Wikimedia (free) + Brave/SerpApi (paid, capped) fetchers, img2dataset wrapper
- `scripts/extract/` — Docling → error-page keyword locator → VLM schema extraction
- `scripts/dedupe/` — sha256 → phash → CLIP → resolution filter
- `scripts/synth/` — 7-segment/LCD renderer + augmentation + homography compositor (smoke-tested end-to-end, works)
- `scripts/redteam/` — PyRIT sticker images, poisoned PDF, poisoned notes
- `scripts/labeling/` — Label Studio config + VLM pre-labeling
- Pushed to `git@github.com:alka0203/field-tech-copilot.git` (private), single commit `711144d`

None of this has been run against real/live data yet except the synth
pipeline smoke test. No manuals collected, no images collected, no eval set
exists.

## Decisions log

(newest first — add to this after every step, don't batch)

- 2026-09-29: Confirmed audience is portfolio/FDE-interview-prep, not a real production tool — shifts the done/good bar toward eval quality + writeup over auth/scale/uptime.
- 2026-09-29: Locked Phase 1 Step 1 problem statement (nameplate ID + error-code decode from a phone photo, grounded in the manufacturer's own manual) as-is, confirmed by user.
- 2026-09-29: Created this context file; chose step-by-step-with-review pacing at user's request.
- 2026-09-27: Pushed initial skeleton to GitHub as private repo `alka0203/field-tech-copilot`.
- 2026-09-27: Chose HVAC vertical (Daikin/Mitsubishi/Carrier) over solar, per user choice when scaffolding started.
- 2026-09-27: Chose to scaffold in a new sibling directory rather than inside recipe-vault, per user choice.

## Next action

Write Phase 1 Step 2: 10-15 real example use-cases/questions a technician
would actually ask, grounded in the brands/model families already in
`sources.yaml` (mix of exact/deterministic, fuzzy/subjective, and edge
cases). Stop for review after drafting.
