"""Resolve a mentioned surface term (or short feedback snippet) to a real SKU.

Layered, cheapest-and-most-certain-first, per the frozen spec:

    1. literal SKU code in the text          -> confidence 1.0
    2. curated multilingual alias table       -> confidence 0.90-0.95
    3. fuzzy / substring against aliases      -> accept at >=0.72
    4. LLM adjudication for leftovers only    -> accept at >=0.60 (opt-in, off by default)
    5. no match                               -> a valid, valuable answer

Layers 1-3 touch no network and need no API key -- the service must run with
layer 4 switched off entirely, since on demo day it might be.

The invariant that matters most: a false match is worse than no match. If a
dietary/texture qualifier is present in the text (gluten free, halal, sugar
free, low sodium, lactose free, vegetarian, nut free, pureed/soft/cannot chew)
and the best-candidate SKU doesn't carry that qualifier, the match is refused
-- `matched_sku` is None, and `near_sku` / `unmet_qualifier` are reported
instead. "We stock bread but not gluten-free bread" beats a silent false
match or a bare null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Optional

from app.skus import ALIASES, SKU_BY_CODE, SKU_CATALOGUE
from app.skus import (
    GLUTEN_FREE,
    HALAL,
    SUGAR_FREE,
    LOW_SODIUM,
    LACTOSE_FREE,
    VEGETARIAN,
    NUT_FREE,
    SOFT_TEXTURE,
)

FUZZY_ACCEPT_THRESHOLD = 0.72
LLM_ACCEPT_THRESHOLD = 0.60

# Phrases that signal a qualifier is being asked for. Deliberately over-inclusive
# and phrased for real beneficiary language (including Singlish), not just the
# clinical term -- "no more teeth" and "damn hard" should trip SOFT_TEXTURE just
# as much as "pureed" does.
QUALIFIER_PATTERNS: dict[str, list[str]] = {
    GLUTEN_FREE: ["gluten free", "gluten-free", "no gluten"],
    HALAL: ["halal"],
    SUGAR_FREE: ["sugar free", "sugar-free", "no sugar", "diabetic"],
    LOW_SODIUM: ["low sodium", "low-sodium", "less salt", "no salt"],
    LACTOSE_FREE: ["lactose free", "lactose-free", "dairy free", "no dairy"],
    VEGETARIAN: ["vegetarian", "no meat", "veg only"],
    NUT_FREE: ["nut free", "nut-free", "no nuts", "peanut allergy"],
    SOFT_TEXTURE: [
        "pureed",
        "puree",
        "soft food",
        "softer food",
        "cannot chew",
        "can't chew",
        "hard to chew",
        "no teeth",
        "no more teeth",
        "damn hard",
        "too hard",
    ],
}

_SKU_CODE_RE = re.compile(r"\b[A-Z]{2,}-[A-Z0-9]+\b")


@dataclass
class MatchResult:
    matched_sku: Optional[str]
    confidence: float
    method: str  # "exact_code" | "alias" | "fuzzy" | "llm" | "qualifier_blocked" | "none"
    near_sku: Optional[str] = None
    unmet_qualifier: Optional[str] = None


def _normalize(text: str) -> str:
    return text.strip().lower()


def _detect_qualifiers(normalized_text: str) -> list[str]:
    found = []
    for tag, phrases in QUALIFIER_PATTERNS.items():
        if any(phrase in normalized_text for phrase in phrases):
            found.append(tag)
    return found


def _match_exact_code(text: str) -> Optional[tuple[str, float]]:
    for code in SKU_BY_CODE:
        if re.search(rf"\b{re.escape(code)}\b", text, flags=re.IGNORECASE):
            return code, 1.0
    return None


def _match_alias(normalized_text: str) -> Optional[tuple[str, float]]:
    # Prefer the longest alias that appears in the text, so "cooking oil"
    # wins over the shorter "oil" when both are present.
    candidates = [
        (alias, sku)
        for alias, sku in ALIASES.items()
        if _alias_present(alias, normalized_text)
    ]
    if not candidates:
        return None
    alias, sku = max(candidates, key=lambda pair: len(pair[0]))
    return sku, 0.93


def _alias_present(alias: str, normalized_text: str) -> bool:
    if re.search(r"[一-鿿]", alias):
        # CJK aliases: no word boundaries, plain substring match.
        return alias in normalized_text
    return re.search(rf"\b{re.escape(alias)}\b", normalized_text) is not None


def _match_fuzzy(normalized_text: str) -> Optional[tuple[str, float]]:
    tokens = re.findall(r"[a-z]+", normalized_text)
    ngrams = set(tokens)
    for size in (2, 3):
        for i in range(len(tokens) - size + 1):
            ngrams.add(" ".join(tokens[i : i + size]))

    best: Optional[tuple[str, float]] = None
    for alias, sku in ALIASES.items():
        if re.search(r"[一-鿿]", alias):
            continue  # fuzzy matching on CJK aliases isn't meaningful here
        for ngram in ngrams:
            # Require the first character to match before scoring. Plain
            # SequenceMatcher.ratio() alone false-matches unrelated real
            # words that happen to sit at short edit-distance from a short
            # alias (e.g. "nice"/"race" -> "rice", "wish"/"dish" -> "fish",
            # "toffee" -> "coffee") at ratios *higher* than genuine typos
            # like "rce" -> "rice" -- there is no single ratio threshold
            # that admits the latter without also admitting the former.
            # This gate is a cheap, evidenced discriminator for that failure
            # mode (see AUDIT.md B1); it does not eliminate every case
            # (documented residual: "race"/"bead"/"beams" still slip past
            # since they share a first letter with the target alias).
            if not ngram or not alias or ngram[0] != alias[0]:
                continue
            ratio = SequenceMatcher(None, ngram, alias).ratio()
            if ratio >= FUZZY_ACCEPT_THRESHOLD and (best is None or ratio > best[1]):
                best = (sku, ratio)
    return best


def match_term(
    text: str,
    llm_adjudicate: Optional[Callable[[str, list[str]], Optional[tuple[str, float]]]] = None,
) -> MatchResult:
    """Resolve one mentioned term (or short feedback snippet) to a SKU.

    `llm_adjudicate`, if given, is called only when layers 1-3 found nothing;
    it must return `(sku_code, confidence)` or `None`. Leave it unset (the
    default) to run fully offline -- this is required, not optional, since
    the service must demo with layer 4 switched off.
    """
    normalized = _normalize(text)

    candidate = _match_exact_code(text)
    method = "exact_code"
    if candidate is None:
        candidate = _match_alias(normalized)
        method = "alias"
    if candidate is None:
        candidate = _match_fuzzy(normalized)
        method = "fuzzy"
    if candidate is None and llm_adjudicate is not None:
        llm_result = llm_adjudicate(text, list(SKU_BY_CODE.keys()))
        if llm_result is not None and llm_result[1] >= LLM_ACCEPT_THRESHOLD:
            candidate = llm_result
            method = "llm"

    if candidate is None:
        return MatchResult(matched_sku=None, confidence=0.0, method="none")

    sku_code, confidence = candidate
    sku_item = SKU_BY_CODE[sku_code]

    for qualifier in _detect_qualifiers(normalized):
        if qualifier not in sku_item.qualifiers:
            return MatchResult(
                matched_sku=None,
                confidence=0.0,
                method="qualifier_blocked",
                near_sku=sku_code,
                unmet_qualifier=qualifier,
            )

    return MatchResult(matched_sku=sku_code, confidence=confidence, method=method)
