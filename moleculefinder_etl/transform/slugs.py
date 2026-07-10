"""URL slugs: deterministic, ascii, collision-safe.

Chemical names lean on Greek letters (alpha/beta/gamma...) and a few symbols, so
we transliterate those to words before dropping non-ascii — otherwise 'β-Carotene'
would collapse to 'carotene' and collide with unrelated names.
"""
from __future__ import annotations
import re
import unicodedata

_slug_strip = re.compile(r"[^a-z0-9]+")

# Greek letters used throughout chemical nomenclature, spelled out.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
}
_SYMBOLS = {"+": "-plus-", "±": "-pm-", "'": "", "′": "", "&": "-and-"}


def _translit(name: str) -> str:
    out = []
    for ch in name:
        lo = ch.lower()
        if lo in _GREEK:
            out.append(_GREEK[lo])
        elif ch in _SYMBOLS:
            out.append(_SYMBOLS[ch])
        else:
            out.append(ch)
    return "".join(out)


def slugify(name: str) -> str:
    """'Caffeine' -> 'caffeine'; 'β-Carotene' -> 'beta-carotene'."""
    norm = _translit(name)
    norm = unicodedata.normalize("NFKD", norm).encode("ascii", "ignore").decode("ascii")
    norm = _slug_strip.sub("-", norm.lower()).strip("-")
    return norm or "molecule"


def unique_slug(name: str, taken: set[str]) -> str:
    """Return a slug not already in `taken`, appending -2, -3, ... on collision.

    Mutates `taken` by adding the returned slug.
    """
    base = slugify(name)
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    taken.add(slug)
    return slug
