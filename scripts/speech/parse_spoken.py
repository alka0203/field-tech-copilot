"""Deterministic parser for spoken HVAC service queries.

Turns an ASR transcript such as

    "Mitsubishi M S Z F H zero nine N A, error P eight"

into {"brand": "mitsubishi", "model_family": "MSZ-FH09NA",
      "error_code": "P8", "question": ""}.

Design rules
------------
* Pure rule-based (regex + number-word handling + fuzzy brand/family matching).
  No LLM, no network, no heavy imports (only stdlib, optional PyYAML,
  optional rapidfuzz).
* NEVER invent a brand / model / code that was not spoken.  Every output field
  is either empty or derived from tokens that are actually in the transcript
  (or, for brand only, inferred from a spoken model-family prefix; that case is
  reported in ``notes``).
* The transcript is UNTRUSTED.  The three structured fields are whitelisted /
  regex-constrained (brand is one of the known brands; model matches
  ``[A-Z0-9-]{1,24}``; code matches ``[A-Z0-9]{1,6}``).  Only ``question`` can
  carry free text and callers must treat it as data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # fuzzy matching is a nice-to-have; fall back to difflib if missing
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz.distance import Levenshtein as _lev

    def _ratio(a: str, b: str) -> float:
        return _fuzz.ratio(a, b)

    def _edit(a: str, b: str) -> int:
        return _lev.distance(a, b)
except Exception:  # pragma: no cover
    import difflib

    def _ratio(a: str, b: str) -> float:
        return 100.0 * difflib.SequenceMatcher(None, a, b).ratio()

    def _edit(a: str, b: str) -> int:
        # crude: good enough for the <=1 check
        if a == b:
            return 0
        sm = difflib.SequenceMatcher(None, a, b)
        return max(len(a), len(b)) - sum(bl.size for bl in sm.get_matching_blocks())

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Brand / family knowledge (sources.yaml is the source of truth; built-ins are
# a fallback + extras that exist in the manuals but not in the yaml list)
# ---------------------------------------------------------------------------

_BUILTIN_BRANDS = {
    "carrier": ["40MAQ", "38MAQB", "25HCE"],
    "daikin": ["FTXS", "FTKF", "FTKX", "CTX", "RMXS", "RXS", "VRV", "SKYAIR"],
    "mitsubishi": ["MSZ", "MUZ", "MXZ", "PUZ", "MSZ-FH", "MSZ-GE"],
}
_EXTRA_FAMILIES = {
    "carrier": ["38MAQ", "25HBC"],
    "daikin": ["FTX", "FTK", "RKS", "FTXM", "FTKM", "FTXR", "FDXS", "FVXS"],
    "mitsubishi": ["MSY", "MUY", "PUY"],
}


def _load_brands() -> dict[str, list[str]]:
    brands = {k: list(v) for k, v in _BUILTIN_BRANDS.items()}
    try:
        import yaml

        data = yaml.safe_load((REPO / "sources.yaml").read_text())
        for b in data.get("brands", []):
            name = str(b["name"]).lower()
            fams = [str(f).upper() for f in b.get("model_families", [])]
            brands[name] = sorted(set(brands.get(name, [])) | set(fams))
    except Exception:
        pass
    for k, v in _EXTRA_FAMILIES.items():
        brands[k] = sorted(set(brands.get(k, [])) | set(v))
    return brands


BRAND_FAMILIES = _load_brands()
BRANDS = sorted(BRAND_FAMILIES)

# first-letter-anchored fuzzy aliases that Whisper is known to produce
_BRAND_ALIASES = {
    "carrier": {"carrier", "carriers", "carrior", "carreer", "carrie"},
    "daikin": {"daikin", "diken", "dikin", "dakin", "daiken", "diakin", "dykin",
               "daikon", "dyken", "dikon", "daykin", "daikan", "dycan", "daiken"},
    "mitsubishi": {"mitsubishi", "mitsubishis", "mitsubushi", "mitsibishi",
                   "mitzubishi", "metsubishi", "mitsu", "mitsubitshi",
                   "mitsubashi", "mitsubisi", "midsubishi", "mitsubischi"},
}
_BRAND_SPLIT_FORMS = {  # two-token forms ("die kin", "mitsu bishi")
    "daikin": {"die kin", "dye kin", "day kin", "dai kin", "dikin", "da kin"},
    "mitsubishi": {"mitsu bishi", "mits ubishi", "mitzu bishi", "mitsu bushi",
                   "mits bishi", "meets ubishi"},
    "carrier": {"carry er", "carrie er"},
}

# ---------------------------------------------------------------------------
# Model-number patterns (matched against the *joined* alphanumeric run)
# ---------------------------------------------------------------------------

_DAIKIN_PFX = ("FTXS|FTKF|FTKX|FTXR|FTXM|FTKM|FDXS|FVXS|RMXS|RXS|RKS|CTX|FTX|FTK")
_MODEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("carrier", re.compile(r"\d{2}(?:MAQB|MAQ|HCE|HBC)")),
    ("mitsubishi", re.compile(
        r"(?P<p>MSZ|MUZ|MSY|MUY)(?P<ser>FH|GE|GL|GS|GF|FS|EF|HM|WN|SF)?"
        r"(?P<size>\d{2})?(?P<suf>NAHZ|NAH|NHA|NKA|NA)?")),
    ("mitsubishi", re.compile(r"(?P<p>MXZ)(?P<body>\d[A-Z]\d{2}(?:NAHZ|NAH|NKA|NA)?)?")),
    ("mitsubishi", re.compile(r"(?P<p>PUZ|PUY)(?P<body>A\d{2}(?:NHAH|NHA|NKA|NHZ)?\d?)?")),
    ("daikin", re.compile(
        rf"(?P<p>{_DAIKIN_PFX})(?P<size>\d{{2}})?"
        r"(?P<suf>LVMA|LVJU|LVMB|HVJU|AXVJU|LVJ|MVJU|LV)?")),
    ("daikin", re.compile(r"VRV|SKYAIR")),
]
# canonical strings eligible for edit-distance-1 matching (>= 4 chars only;
# 3-letter prefixes like MSZ/MXZ/PUZ differ by one letter, so exact only)
_FUZZY_FAMILIES = [("carrier", "40MAQ"), ("carrier", "38MAQB"), ("carrier", "25HCE"),
                   ("daikin", "FTXS"), ("daikin", "FTKF"), ("daikin", "FTKX"),
                   ("daikin", "RMXS")]
_PREFIX_RE = re.compile(rf"^(?:{_DAIKIN_PFX}|MSZ|MUZ|MSY|MUY|MXZ|PUZ|PUY|VRV)")
# Noisy-audio confusions seen in practice: M<->N, Z<->C/V (plain 'put'/'mud'/'pub'
# style words are deliberately NOT included).  Only exact 3-letter prefixes.
def _prefix_variants() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in ("MSZ", "MUZ", "MXZ", "PUZ"):
        for i, ch in enumerate(p):
            subs = {"M": "N", "Z": "CV"}.get(ch, "")
            for sub in subs:
                out[p[:i] + sub + p[i + 1:]] = p
    return out


_PREFIX_VARIANTS = _prefix_variants()
_MODEL_BITS = {  # all-letter tokens that may be pieces of a model number
    "msz", "muz", "msy", "muy", "mxz", "puz", "puy", "ftxs", "ftkf", "ftkx",
    "ftxr", "ftxm", "ftkm", "ftx", "ftk", "rxs", "rks", "rmxs", "ctx", "fdxs",
    "fvxs", "vrv", "skyair", "maq", "maqb", "hce", "hbc", "fh", "ge", "gl", "gs",
    "gf", "fs", "ef", "hm", "wn", "sf", "lvma", "lvju", "lvmb", "hvju", "axvju",
    "nha", "nka", "nahz", "nah", "nhz",
}

# ---------------------------------------------------------------------------
# Spoken-token vocabularies
# ---------------------------------------------------------------------------

_ONES = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMW = set(_ONES) | set(_TEENS) | set(_TENS) | {"hundred"}
# only treated as digits right after a lone code letter ("E to" is rare, "go to" is not)
_HOMO = {"to": 2, "too": 2, "for": 4, "fore": 4, "ate": 8, "won": 1, "tree": 3,
         "sex": 6, "nein": 9}

_LETTER_NAMES = {  # unambiguous spoken letter names
    "bee": "b", "dee": "d", "eff": "f", "ef": "f", "gee": "g", "aitch": "h",
    "jay": "j", "kay": "k", "ell": "l", "em": "m", "pee": "p", "queue": "q",
    "cue": "q", "ess": "s", "vee": "v", "zee": "z", "zed": "z", "ex": "x",
    "cee": "c", "ee": "e", "ay": "a",
}
_AMBIG_LETTERS = {"you": "u", "why": "y", "sea": "c", "eye": "i", "tea": "t",
                  "are": "r", "en": "n"}
_NATO = {"alpha": "a", "alfa": "a", "bravo": "b", "charlie": "c", "delta": "d",
         "echo": "e", "foxtrot": "f", "golf": "g", "hotel": "h", "india": "i",
         "juliet": "j", "juliett": "j", "kilo": "k", "lima": "l", "mike": "m",
         "november": "n", "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r",
         "sierra": "s", "tango": "t", "uniform": "u", "victor": "v",
         "whiskey": "w", "xray": "x", "yankee": "y", "zulu": "z"}

_STRONG_TRIGGERS = {"error", "errors", "code", "codes", "fault", "alarm", "flash",
                    "flashes", "flashing", "blinking", "blinks", "blink",
                    "displaying", "display", "displays", "showing", "shows",
                    "reads", "reading", "says", "lockout", "diagnostic", "failure"}
_TRIGGER_FILLER = {"number", "no", "is", "of", "was", "are", "the", "a", "an", "on",
                   "it", "its", "it's", "as", "for", "to", "at", "with", "i", "get",
                   "getting", "got", "see", "seeing", "have", "has", "i'm", "im",
                   "showing", "shows", "reads", "says", "me", "us", "unit", "led",
                   "screen", "remote", "indoor", "outdoor", "this", "that", "and",
                   "then", "now", "keeps", "keep", "giving", "gives", "give",
                   "throwing", "throws", "code", "codes"}
# 2-letter alphabetic codes that really exist (only accepted right after a trigger)
_LETTER_ONLY_CODES = {"EC", "UA", "UH", "AJ", "AH", "CA", "LC"}
_CODE_LETTERS_UNTRIGGERED = set("CEFHJLPU")
_UNIT_WORDS = {"year", "years", "ton", "tons", "inch", "inches", "degree", "degrees",
               "volt", "volts", "amp", "amps", "psi", "foot", "feet", "hour", "hours",
               "minute", "minutes", "second", "seconds", "percent", "unit", "units",
               "zone", "zones", "btu", "btus", "times", "time", "days", "day",
               "weeks", "week", "months", "month", "hz", "pounds", "ohms", "seer",
               "bar", "kpa", "cfm", "feet", "f", "c"}

_STOP = set("""a an the and or but so if then than that this these those there here
is are was were be been being am do does did done doing have has had having i me my
mine we us our you your he she it its they them their of on in at to for from with
without by as into over under up down out off about please hi hello hey uh um uhh
umm okay ok yeah yes no not just also very really still again now ever
what whats how why when where which who whom can could should would will shall may
might must get gets got getting keeps keep kept going goes gone showing shows show
shown displaying display displays says say said reads read reading flashing blinking
flash blinks error errors code codes fault faults alarm model models number brand
unit units need needs want wants help tell give gives mean means meaning
number no""".split())

_SENT_FILLER_WORDS = _STOP


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParsedQuery:
    brand: str = ""
    model_family: str = ""
    error_code: str = ""
    question: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"brand": self.brand, "model_family": self.model_family,
                "error_code": self.error_code, "question": self.question}


@dataclass
class _Tok:
    raw: str
    low: str
    idx: int


@dataclass
class _Item:
    """kind: 'frag' (alnum fragment, text upper-case) | 'word' (plain word)."""
    kind: str
    text: str
    idxs: tuple[int, ...]
    consumed: bool = False


# ---------------------------------------------------------------------------
# Step 0: tokenisation
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[_Tok]:
    text = text.replace("’", "'")
    text = re.sub(r"(?i)\bsky\s+air\b", "skyair", text)
    # hyphens / slashes / dots / commas are token separators ("E-one", "MSZ-FH09NA")
    text = re.sub(r"[-‐-―/.,;:!?()\[\]\"_]+", " ", text)
    toks: list[_Tok] = []
    for m in re.finditer(r"[A-Za-z0-9']+", text):
        raw = m.group(0).strip("'")
        if not raw:
            continue
        low = raw.lower()
        if low.endswith("'s"):
            low = low[:-2]
            raw = raw[:-2]
        toks.append(_Tok(raw, low, len(toks)))
    return toks


# ---------------------------------------------------------------------------
# Step 1: brand
# ---------------------------------------------------------------------------

def _brand_for_token(low: str) -> tuple[str, bool] | None:
    """Return (brand, was_fuzzy) for a single token, or None."""
    if len(low) < 4 or not low.isalpha():
        return None
    for b, aliases in _BRAND_ALIASES.items():
        if low in aliases:
            return b, low != b
    best: tuple[float, str] = (0.0, "")
    for b in BRANDS:
        if low[0] != b[0]:
            continue
        r = _ratio(low, b)
        if r > best[0]:
            best = (r, b)
    if best[0] >= 80:
        return best[1], True
    return None


def _find_brand(toks: list[_Tok], notes: list[str]) -> tuple[str, set[int]]:
    hits: list[tuple[str, tuple[int, ...]]] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        r = _brand_for_token(t.low)
        if r:
            b, fuzzy = r
            used = [t.idx]
            if b == "mitsubishi" and i + 1 < len(toks) and toks[i + 1].low == "electric":
                used.append(toks[i + 1].idx)
            if fuzzy:
                notes.append(f"heard '{t.raw}' -> brand {b}")
            hits.append((b, tuple(used)))
            i += len(used)
            continue
        if i + 1 < len(toks):
            pair = f"{t.low} {toks[i + 1].low}"
            matched = next((b for b, forms in _BRAND_SPLIT_FORMS.items() if pair in forms), None)
            if matched is None:
                joined = t.low + toks[i + 1].low
                if len(joined) >= 6 and joined.isalpha():
                    rr = _brand_for_token(joined)
                    # require the pair to be two short fragments, not two real words
                    if rr and len(t.low) <= 5 and len(toks[i + 1].low) <= 6:
                        matched = rr[0]
            if matched:
                notes.append(f"heard '{t.raw} {toks[i + 1].raw}' -> brand {matched}")
                hits.append((matched, (t.idx, toks[i + 1].idx)))
                i += 2
                continue
        i += 1
    if not hits:
        return "", set()
    chosen = hits[0][0]
    distinct = {h[0] for h in hits}
    if len(distinct) > 1:
        notes.append("several brands heard: " + ", ".join(sorted(distinct)) + f"; using {chosen}")
    consumed = {ix for b, ids in hits for ix in ids}
    return chosen, consumed


# ---------------------------------------------------------------------------
# Step 2: spoken numbers / letters -> fragments
# ---------------------------------------------------------------------------

def _numwords_to_digits(words: list[str]) -> str:
    out = ""
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if w in _ONES:
            out += str(_ONES[w])
        elif w in _TEENS:
            out += str(_TEENS[w])
        elif w in _TENS:
            v = _TENS[w]
            if i + 1 < n and words[i + 1] in _ONES and _ONES[words[i + 1]] > 0:
                v += _ONES[words[i + 1]]
                i += 1
            out += str(v)
        elif w == "hundred":
            if out and out[-1].isdigit():
                d = out[-1]
                out = out[:-1]
                base = int(d) * 100
                # "one hundred twenty three"
                rest_words = words[i + 1:]
                if rest_words and (rest_words[0] in _TENS or rest_words[0] in _TEENS
                                   or rest_words[0] in _ONES):
                    rest = _numwords_to_digits(rest_words[:2] if rest_words[0] in _TENS
                                               else rest_words[:1])
                    consumed = 2 if (rest_words[0] in _TENS and len(rest_words) > 1
                                     and rest_words[1] in _ONES and _ONES[rest_words[1]] > 0) else 1
                    out += str(base + int(rest))
                    i += consumed
                else:
                    out += str(base)
            else:
                out += "100"
        i += 1
    return out


def _is_numtok(t: _Tok) -> bool:
    return t.low in _NUMW and t.low != "oh"


def _build_items(toks: list[_Tok], brand_consumed: set[int]) -> tuple[list[_Item], set[int]]:
    extra: set[int] = set()
    items: list[_Item] = []
    n = len(toks)
    i = 0

    def prev_is_frag() -> _Item | None:
        return items[-1] if items and items[-1].kind == "frag" else None

    def prev_ok_for_ambiguous() -> bool:
        if not items:
            return True
        p = items[-1]
        if p.kind == "frag":
            return True
        return p.text in _STRONG_TRIGGERS or p.text in _TRIGGER_FILLER

    def next_is_number(j: int) -> bool:
        if j >= n:
            return False
        nl = toks[j].low
        return nl in _NUMW or nl.isdigit() or nl in _HOMO

    while i < n:
        t = toks[i]
        low = t.low
        if t.idx in brand_consumed:
            items.append(_Item("word", "\x00brand", (t.idx,), consumed=True))
            i += 1
            continue

        # "E as in echo" -> E
        if low == "as" and i + 2 < n and toks[i + 1].low == "in":
            p = prev_is_frag()
            nxt = toks[i + 2].low
            if p and len(p.text) == 1 and nxt[:1] == p.text.lower():
                extra.update((t.idx, toks[i + 1].idx, toks[i + 2].idx))
                i += 3
                continue

        # number words
        is_num = _is_numtok(t)
        if low == "oh":
            is_num = (i + 1 < n and _is_numtok(toks[i + 1])) or \
                     (i > 0 and (_is_numtok(toks[i - 1]) or toks[i - 1].low.isdigit()
                                 or (items and items[-1].kind == "frag")))
        if is_num:
            j = i
            words: list[str] = []
            while j < n and toks[j].idx not in brand_consumed and (
                    _is_numtok(toks[j]) or toks[j].low == "oh"):
                words.append(toks[j].low)
                j += 1
            digits = _numwords_to_digits(words)
            if digits:
                items.append(_Item("frag", digits, tuple(x.idx for x in toks[i:j])))
                i = j
                continue

        # homophone digits right after a lone code letter ("U for" -> U4)
        pf = prev_is_frag()
        if low in _HOMO and pf and len(pf.text) == 1 and pf.text.isalpha() \
                and pf.text not in "AI":
            items.append(_Item("frag", str(_HOMO[low]), (t.idx,)))
            i += 1
            continue

        # letter names
        if low in _LETTER_NAMES:
            items.append(_Item("frag", _LETTER_NAMES[low].upper(), (t.idx,)))
            i += 1
            continue
        if low in _AMBIG_LETTERS and prev_ok_for_ambiguous() and next_is_number(i + 1):
            items.append(_Item("frag", _AMBIG_LETTERS[low].upper(), (t.idx,)))
            i += 1
            continue
        if low in _NATO and (next_is_number(i + 1) or prev_is_frag()):
            items.append(_Item("frag", _NATO[low].upper(), (t.idx,)))
            i += 1
            continue

        # raw alnum fragments
        if low.isdigit():
            items.append(_Item("frag", low, (t.idx,)))
        elif len(low) == 1 and low.isalpha():
            items.append(_Item("frag", low.upper(), (t.idx,)))
        elif low.isalnum() and any(c.isdigit() for c in low) and any(c.isalpha() for c in low):
            items.append(_Item("frag", low.upper(), (t.idx,)))
        elif low in _MODEL_BITS or low.upper() in _PREFIX_VARIANTS:
            items.append(_Item("frag", low.upper(), (t.idx,)))
        elif (pf is not None and pf.text.isdigit() and len(pf.text) == 2
              and low.isalpha() and 3 <= len(low) <= 4
              and any(low[0].upper() == f[0] and _edit(low.upper(), f) <= 1
                      for f in ("MAQ", "MAQB", "HCE"))):
            # "forty MAC" (ASR slip for 40MAQ) -> fuzzy-matched later
            items.append(_Item("frag", low.upper(), (t.idx,)))
        elif (t.raw.isupper() and t.raw.isalpha() and 2 <= len(t.raw) <= 6
              and pf is not None and _PREFIX_RE.match(_run_text(items))
              and low not in _STOP and low not in _STRONG_TRIGGERS):
            # "FTXS35 LVMA": upper-case tail right after a model prefix
            items.append(_Item("frag", t.raw.upper(), (t.idx,)))
        else:
            items.append(_Item("word", low, (t.idx,)))
        i += 1
    return items, extra


def _run_text(items: list[_Item]) -> str:
    out: list[str] = []
    for it in reversed(items):
        if it.kind != "frag":
            break
        out.append(it.text)
    return "".join(reversed(out))


# ---------------------------------------------------------------------------
# Step 3: segments (runs of fragments), model extraction
# ---------------------------------------------------------------------------

# A segment is ('word', text, idxs, consumed) or ('run', [(char, idx), ...]).

def _segments(items: list[_Item]) -> list[list]:
    segs: list[list] = []
    cur: list[tuple[str, tuple[int, ...]]] = []

    def flush():
        nonlocal cur
        if cur:
            joined = "".join(c for c, _ in cur)
            if joined in ("A", "I"):                       # the English words
                segs.append(["word", joined.lower(), cur[0][1], False])
            else:
                segs.append(["run", cur])
        cur = []

    for it in items:
        if it.kind == "frag":
            for ch in it.text:
                cur.append((ch, it.idxs))
        else:
            flush()
            segs.append(["word", it.text, it.idxs, it.consumed])
    flush()
    return segs


def _fmt_model(brand: str, m: re.Match) -> str:
    g = m.groupdict()
    if brand == "carrier":
        return m.group(0)
    if brand == "mitsubishi":
        pfx = g["p"]
        rest = "".join(g.get(k) or "" for k in ("ser", "size", "suf", "body"))
        return f"{pfx}-{rest}" if rest else pfx
    if brand == "daikin":
        if "p" in g and g["p"]:
            return "".join(g.get(k) or "" for k in ("p", "size", "suf"))
        return m.group(0)
    return m.group(0)


def _extract_model(segs: list[list], notes: list[str]):
    """Find the first model number inside the runs.  Returns
    (model, brand_of_model, consumed_idx_set, new_segs)."""
    best = None  # (seg_index, start, end, brand, text, fuzzy_note)
    for si, seg in enumerate(segs):
        if seg[0] != "run":
            continue
        chars = seg[1]
        joined = "".join(c for c, _ in chars)
        cands = []
        for brand, pat in _MODEL_PATTERNS:
            m = pat.search(joined)
            if m and m.end() > m.start():
                cands.append((m.start(), brand, m))
        vnote = None
        if not cands:                          # noisy-audio prefix confusions (NSZ -> MSZ)
            for i in range(len(joined) - 2):
                w = joined[i:i + 3]
                if w in _PREFIX_VARIANTS:
                    fixed = joined[:i] + _PREFIX_VARIANTS[w] + joined[i + 3:]
                    for brand, pat in _MODEL_PATTERNS:
                        m = pat.search(fixed)
                        if m and m.start() == i and m.end() > m.start():
                            cands.append((m.start(), brand, m))
                            vnote = f"heard '{w}' -> {_PREFIX_VARIANTS[w]}"
                            break
                    if cands:
                        break
        if cands:
            cands.sort(key=lambda x: x[0])
            _, brand, m = cands[0]
            text, end = _fmt_model(brand, m), m.end()
            if vnote:
                notes.append(vnote)
            if brand == "carrier" and text.endswith("MAQ"):
                nxt = joined[end:end + 1]
                if nxt and nxt in "VDPEGTZ" and not joined[end + 1:end + 2].isdigit():
                    notes.append(f"heard '{text}{nxt}' -> {text}B")
                    text, end = text + "B", end + 1
            best = (si, m.start(), end, brand, text, None)
            break
        # fuzzy: edit distance 1 against long canonical families
        fz = None
        for brand, fam in _FUZZY_FAMILIES:
            L = len(fam)
            for ln in (L, L - 1, L + 1):
                for st in range(0, len(joined) - ln + 1):
                    w = joined[st:st + ln]
                    if w[0] != fam[0] or (fam[0].isdigit() and w[:2] != fam[:2]):
                        continue
                    if _edit(w, fam) == 1 and (fz is None or st < fz[0]):
                        fz = (st, st + ln, brand, fam, w)
        if fz:
            st, en, brand, fam, w = fz
            best = (si, st, en, brand, fam, f"heard model '{w}' -> {fam}")
            break
    if best is None:
        return "", "", set(), segs
    si, st, en, brand, text, fnote = best
    if fnote:
        notes.append(fnote)
    chars = segs[si][1]
    consumed = {ix for _, ids in chars[st:en] for ix in ids}
    left, right = chars[:st], chars[en:]
    new = segs[:si]
    # trailing pieces that carry only an index (empty char) stay with the model
    left = [c for c in left if c[0]]
    if left:
        new.append(["run", left])
    new.append(["word", "\x00model", tuple(consumed), True])
    right = [c for c in right if c[0]]
    if right:
        new.append(["run", right])
    new.extend(segs[si + 1:])
    return text, brand, consumed, new


# ---------------------------------------------------------------------------
# Step 4: error code
# ---------------------------------------------------------------------------

_LETTER_DIGITS = re.compile(r"[A-Z]\d{1,3}")


def _trigger_before(segs: list[list], si: int) -> bool:
    saw_strong = False
    steps = 0
    for k in range(si - 1, -1, -1):
        seg = segs[k]
        if seg[0] != "word" or seg[3]:
            break
        w = seg[1]
        if w in _STRONG_TRIGGERS:
            saw_strong = True
        elif w not in _TRIGGER_FILLER:
            break
        steps += 1
        if steps >= 5:
            break
    return saw_strong


def _next_word(segs: list[list], si: int) -> str:
    if si + 1 < len(segs) and segs[si + 1][0] == "word" and not segs[si + 1][3]:
        return segs[si + 1][1]
    return ""


def _extract_code(segs: list[list], notes: list[str]):
    cands: list[tuple[bool, str, list[int]]] = []   # (triggered, code, idxs)
    for si, seg in enumerate(segs):
        if seg[0] != "run":
            continue
        chars = [c for c in seg[1] if c[0]]
        s = "".join(c for c, _ in chars)
        idxs = [ids for _, ids in chars]
        trig = _trigger_before(segs, si)
        # letter+digits (possibly several codes back to back)
        pieces = re.findall(r"[A-Z]\d{1,3}", s)
        if pieces and "".join(pieces) == s:
            if len(pieces) == 1:
                letter = s[0]
                if trig or letter in _CODE_LETTERS_UNTRIGGERED:
                    cands.append((trig, s, idxs))
            else:
                if trig or pieces[0][0] in _CODE_LETTERS_UNTRIGGERED:
                    notes.append("several codes heard in one phrase: " + ", ".join(pieces))
                    cands.append((trig, pieces[0], idxs[:len(pieces[0])]))
            continue
        if trig and re.fullmatch(r"\d{1,4}", s):
            if _next_word(segs, si) in _UNIT_WORDS:
                continue
            cands.append((True, s, idxs))
            continue
        if trig and s in _LETTER_ONLY_CODES:
            cands.append((True, s, idxs))
    if not cands:
        return "", set()
    trig_c = [c for c in cands if c[0]]
    pool = trig_c or cands
    chosen = pool[0]
    distinct = []
    for c in cands:
        if c[1] not in distinct:
            distinct.append(c[1])
    if len(distinct) > 1:
        notes.append(f"several codes heard: {', '.join(distinct)}; using {chosen[1]}")
    return chosen[1], {ix for ids in chosen[2] for ix in ids}


# ---------------------------------------------------------------------------
# Step 5: leftover free-text question
# ---------------------------------------------------------------------------

def _question(toks: list[_Tok], consumed: set[int]) -> str:
    left = [t for t in toks if t.idx not in consumed]
    # trim leading / trailing stop words
    while left and left[0].low in _STOP:
        left.pop(0)
    while left and left[-1].low in _STOP:
        left.pop()
    content = [t for t in left if t.low not in _STOP and len(t.low) > 1]
    if len(content) < 2:
        return ""
    return " ".join(t.raw for t in left)[:300]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_HVAC_STEMS = (
    "compress", "fan", "motor", "thermostat", "thermistor", "sensor", "refrigerant",
    "pressure", "coil", "filter", "drain", "leak", "freez", "frost", "ice", "icing",
    "cool", "heat", "defrost", "noise", "noisy", "vibrat", "trip", "breaker", "power",
    "capacitor", "contactor", "inverter", "pcb", "board", "wiring", "wire", "valve",
    "evaporator", "condenser", "outdoor", "indoor", "airflow", "remote", "led",
    "blink", "flash", "reset", "error", "fault", "alarm", "cycl", "short", "shut",
    "start", "charge", "superheat", "subcool", "communicat", "relay", "fuse", "lockout",
    "overload", "current", "voltage", "temperature", "diagnos",
)


def is_hvac_question(question: str) -> bool:
    """Cheap domain gate: does a free-form spoken question mention anything HVAC-ish?
    Used to avoid answering off-topic / injection-style chatter from the manuals."""
    low = (question or "").lower()
    toks = re.findall(r"[a-z]+", low)
    return any(t.startswith(st) for t in toks for st in _HVAC_STEMS)

def _brand_of_model(model: str) -> str:
    for b, fams in BRAND_FAMILIES.items():
        if any(model.upper().startswith(f.split("-")[0]) for f in fams):
            return b
    return ""


def parse_spoken(text: str) -> ParsedQuery:
    """Parse an ASR transcript into brand / model_family / error_code / question."""
    pq = ParsedQuery()
    text = (text or "").strip()
    if not text:
        return pq
    toks = _tokenize(text)
    if not toks:
        return pq

    brand, brand_idx = _find_brand(toks, pq.notes)
    items, extra_idx = _build_items(toks, brand_idx)
    segs = _segments(items)
    model, model_brand, model_idx, segs = _extract_model(segs, pq.notes)
    code, code_idx = _extract_code(segs, pq.notes)

    if model and not brand and model_brand:
        brand = model_brand
        pq.notes.append(f"brand {brand} inferred from model {model}")
    elif model and brand and model_brand and model_brand != brand:
        pq.notes.append(f"model {model} is normally a {model_brand} model but brand heard was {brand}")

    pq.brand = brand
    pq.model_family = model
    pq.error_code = code
    consumed = brand_idx | model_idx | code_idx | extra_idx
    pq.question = _question(toks, consumed)

    if not (pq.brand or pq.model_family or pq.error_code):
        words = [t for t in toks if t.low.isalpha()]
        if len(words) >= 3:       # fallback: hand the raw transcript over as the question
            pq.question = text[:300]
            pq.notes.append("no brand/model/code recognised; using raw transcript as question")
    # defence in depth: structured fields must look like what we claim they are
    if not re.fullmatch(r"[A-Z0-9-]{1,24}", pq.model_family or "X"):
        pq.model_family = ""
    if not re.fullmatch(r"[A-Z0-9]{1,6}", pq.error_code or "X"):
        pq.error_code = ""
    if pq.brand and pq.brand not in BRANDS:
        pq.brand = ""
    return pq


if __name__ == "__main__":  # tiny CLI: python parse_spoken.py "carrier forty M A Q error E one"
    import json
    import sys

    p = parse_spoken(" ".join(sys.argv[1:]))
    print(json.dumps({**p.as_dict(), "notes": p.notes}, indent=2))
