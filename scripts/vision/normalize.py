"""Text normalization for OCR/VLM outputs: error codes, brands, model strings.

Error-code OCR confusion repair is deliberately conservative. A code is
assumed to be <letter prefix><digits> (E1, U4, F28, P8) or all digits (45).
We only swap look-alike characters where the format makes the intended
character unambiguous:

  * the FIRST character is never touched when it is a letter (it is the
    prefix; 'S1' and 'B2' are real-looking codes);
  * characters AFTER a letter prefix must be digits, so O->0, I/l->1, S->5,
    B->8, Z->2 are applied there (E1O -> E10, ES -> E5);
  * if the first character is a digit the whole code is numeric, so the same
    swaps apply to every position (4S -> 45).
  * uppercase 'L' is never mapped (it is a legitimate prefix: L3).

Every change is returned so callers can log it into `warnings`.
"""
from __future__ import annotations

import re

# letter -> digit it is most likely a misread of
TO_DIGIT = {"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8", "Z": "2"}

CODE_RE = re.compile(r"^[A-Z]{1,2}\d{1,3}$|^\d{1,3}$")

BRAND_ALIASES = {
    "carrier": "carrier", "bryant": "carrier",
    "daikin": "daikin",
    "mitsubishi": "mitsubishi", "mitsubishi electric": "mitsubishi", "mitsubishi electric trane": "mitsubishi",
    "mitsubishielectric": "mitsubishi",
}


def normalize_error_code(raw: str) -> tuple[str, list[str]]:
    """Return (normalized_code, changes). Empty/garbage input returns ("", [])."""
    if not raw:
        return "", []
    s = re.sub(r"[\s\-_.:]+", "", str(raw).strip())
    if not s:
        return "", []
    if CODE_RE.match(s.upper()):
        return s.upper(), []          # already a valid code: never touch it (AB1 stays AB1)
    chars = list(s)
    changes: list[str] = []
    start = 0 if chars[0].isdigit() else 1   # letter prefix is preserved
    if len(chars) > 4 or any(not (c.isdigit() or c in TO_DIGIT) for c in chars[start:]):
        return s.upper(), []          # a non-lookalike letter after the prefix: not unambiguous, leave it
    for i in range(start, len(chars)):
        c = chars[i]
        if not c.isdigit() and c in TO_DIGIT:
            changes.append(f"error_code char {i + 1}: '{c}'->'{TO_DIGIT[c]}' (OCR confusion)")
            chars[i] = TO_DIGIT[c]
    out = "".join(chars).upper()
    if not CODE_RE.match(out):
        return s.upper(), []          # could not make it fit the format: report as-is
    return out, changes


def normalize_brand(raw: str) -> str:
    b = re.sub(r"\s+", " ", (raw or "").strip().lower())
    if b in BRAND_ALIASES:
        return BRAND_ALIASES[b]
    for k, v in BRAND_ALIASES.items():
        if k in b:
            return v
    return b


# --- model strings ---------------------------------------------------------

# prefix -> (brand, family-regex)
MODEL_FAMILIES: list[tuple[str, str, str]] = [
    ("carrier", r"40MAQ", "40MAQ"),
    ("carrier", r"38MAQB?", "38MAQ"),
    ("carrier", r"25HCE", "25HCE"),
    ("daikin", r"FTXS", "FTXS"),
    ("daikin", r"FTKX", "FTKX"),
    ("daikin", r"RMXS", "RMXS"),
    ("daikin", r"CTX", "CTX"),
    ("mitsubishi", r"MSZ[- ]?[A-Z]{2}", None),
    ("mitsubishi", r"MXZ", "MXZ"),
    ("mitsubishi", r"PUZ", "PUZ"),
    ("mitsubishi", r"MSZ", "MSZ"),
]

# A full model string: family prefix + remainder of alphanumerics/hyphens
MODEL_STRING_RE = re.compile(
    r"\b(?:" + "|".join(p for _, p, _ in MODEL_FAMILIES) + r")-?[A-Z0-9][A-Z0-9\-/]{1,14}\b"
    r"|\b(?:" + "|".join(p for _, p, _ in MODEL_FAMILIES) + r")\b"
)


def split_model(model: str) -> tuple[str, str]:
    """model string -> (brand, family). ("", "") if prefix unknown."""
    m = re.sub(r"\s+", " ", (model or "").upper().strip())
    for brand, pat, fam in MODEL_FAMILIES:
        mm = re.match(pat, m.replace("MSZ ", "MSZ-"))
        if mm:
            family = fam or mm.group(0).replace(" ", "-")
            return brand, family
    return "", ""


def norm_model_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())
