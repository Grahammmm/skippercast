"""Normalisation for entity resolution (design section 7, step 1).

- ``name_norm``: the ``fleet_name_screen`` rule in ``dist/data/ais-evidence.json``
  (upper-case, keep only A-Z and 0-9, exact comparison), after first dropping a
  leading ``THE``, ``M/V`` or ``F/V`` and turning a trailing roman numeral into
  digits. ``NEW`` is kept: New Seaforth is not Seaforth.
- ``phone_e164``: a North American number (or one already in ``+`` form) to E.164.
- ``clean_url``: an https URL without tracking parameters or fragment.
- ``slugify`` and ``jaro_winkler`` for slugs and fuzzy name scores.

Nothing here is specific to one state.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["clean_url", "is_new_variant", "jaro_winkler", "name_norm", "name_similarity", "phone_e164", "roman_to_int",
           "slugify"]

PREFIXES = ("THE", "M/V", "F/V", "M.V.", "F.V.")
ROMAN = re.compile(r"^(?=[IVX]+$)X{0,3}(IX|IV|V?I{0,3})$")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}
TRACKING = re.compile(r"^(utm_[a-z0-9_]+|gclid|gbraid|wbraid|dclid|fbclid|msclkid|mc_cid|mc_eid|_ga|_gl|igshid|yclid|ref_src)$",
                      re.IGNORECASE)


def _ascii(text: str) -> str:
    """Accents dropped (Niña -> Nina) so the A-Z rule keeps the letter."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def roman_to_int(token: str) -> int | None:
    """1-39 for a roman numeral of I, V and X, else None."""
    token = token.upper()
    if not token or not ROMAN.match(token):
        return None
    total = 0
    for char, after in zip(token, token[1:] + " "):
        value = ROMAN_VALUES[char]
        total += -value if after != " " and ROMAN_VALUES[after] > value else value
    return total


def _tokens(name: str) -> list[str]:
    tokens = _ascii(name).upper().split()
    while len(tokens) > 1 and tokens[0] in PREFIXES:
        tokens = tokens[1:]
    if len(tokens) > 1:  # a trailing numeral only: "Sea Example II" -> 2, a lone "X" stays a name
        number = roman_to_int(re.sub(r"[^A-Z]", "", tokens[-1]) if re.fullmatch(r"[IVX]+\.?", tokens[-1]) else "")
        if number is not None:
            tokens[-1] = str(number)
    return tokens


def name_norm(name: str) -> str:
    """The comparison form of a vessel name: upper-case A-Z and 0-9 only ('' when nothing is left)."""
    return re.sub(r"[^A-Z0-9]", "", "".join(_tokens(name or "")))


def is_new_variant(a: str, b: str) -> bool:
    """True when one normalised name is the other with ``NEW`` in front (New Seaforth vs Seaforth)."""
    return a != b and (a == "NEW" + b or b == "NEW" + a)


def jaro_winkler(a: str, b: str, prefix_scale: float = 0.1) -> float:
    """Jaro-Winkler similarity, 0-1 (1.0 for equal strings)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(0, max(len(a), len(b)) // 2 - 1)
    a_hit, b_hit = [False] * len(a), [False] * len(b)
    matches = 0
    for i, char in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_hit[j] and b[j] == char:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    a_seq = [c for c, hit in zip(a, a_hit) if hit]
    b_seq = [c for c, hit in zip(b, b_hit) if hit]
    transpositions = sum(x != y for x, y in zip(a_seq, b_seq)) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)


def name_similarity(a: str, b: str) -> float:
    """Jaro-Winkler on two normalised names; 0 for a NEW variant, which is a different boat."""
    if is_new_variant(a, b):
        return 0.0
    return jaro_winkler(a, b)


def phone_e164(text: str | None, country: str = "1") -> str | None:
    """E.164 form of a phone number, or None when it cannot be read as one.

    Ten digits are taken as a North American number (``country``); a leading
    ``+`` keeps its own country code. Extensions (``x123``, ``ext. 4``) are dropped.
    """
    if not isinstance(text, str):
        return None
    main = re.split(r"(?i)\s*(?:x|ext\.?|extension)\s*\d+\s*$", text.strip())[0]
    digits = re.sub(r"\D", "", main)
    if main.startswith("+"):
        number = "+" + digits
    elif len(digits) == 10:
        number = "+" + country + digits
    elif len(digits) == 11 and digits.startswith(country):
        number = "+" + digits
    else:
        return None
    return number if re.fullmatch(r"\+[1-9]\d{6,14}", number) else None


def clean_url(url: str | None) -> str | None:
    """An https URL with a lower-case host, without tracking parameters or fragment; None if not https."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not host or parts.username or parts.password:
        return None
    netloc = host.lower() + (f":{parts.port}" if parts.port else "")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)])
    return urlunsplit(("https", netloc, parts.path or "/", query, ""))


def slugify(text: str, limit: int = 60) -> str:
    """Lower-case ASCII words joined by '-' (at most ``limit`` characters, never ending in '-')."""
    words = re.findall(r"[a-z0-9]+", _ascii(text or "").lower())
    slug = "-".join(words)[:limit].strip("-")
    return slug or "vessel"
