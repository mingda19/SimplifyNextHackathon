"""Extraction pipeline: raw beneficiary feedback -> the frozen extraction contract.

Two independent signals, per README's "On trained NLP model" constraint:

1. Claude structured extraction (this module's main job) -- handles the messy
   multilingual reality (Singlish, Mandarin, Malay, Tamil, typos, voice-transcription
   noise) and does the actual field extraction.
2. A pretrained HuggingFace sentiment classifier (DistilBERT SST-2) as a cheap
   second opinion on `sentiment` only. SST-2 is trained on English movie
   reviews -- it is unreliable on Singlish/Mandarin and is never treated as
   ground truth. A disagreement just flags the row for human review.

Every extraction is validated against closed vocabularies (see the *_VOCAB
constants below) via Pydantic before it's trusted. If the first call produces
something that fails validation, we retry exactly once with the validation
error fed back into the conversation, then give up and mark the row failed --
the raw text is never lost either way, since it was already committed by
POST /feedback before this ever runs.

`mentioned_skus` stored on the row is NOT the model's raw guess -- it's what
app.matcher.match_term resolves from the model's `mentioned_terms`, run
offline (layers 1-3 only; layer 4 is opt-in and off by default, see
app/matcher.py). That's the authoritative join key M's aggregation depends on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.config import settings
from app.matcher import match_term

logger = logging.getLogger("feedback.extract")

SENTIMENT_VOCAB = ("negative", "neutral", "positive")
LANG_VOCAB = ("en", "zh", "ms", "ta", "other")
CATEGORY_VOCAB = (
    "staples",
    "dietary_accessibility",
    "soft_foods",
    "hygiene",
    "produce",
    "protein",
    "beverages",
    "other",
)

URGENCY_RUBRIC = """\
Urgency is 1-5. Anchor to this rubric, not vibes -- the ranking downstream
multiplies frequency x urgency, so drift here corrupts every run:

1 = positive or neutral feedback; no unmet need
2 = a mild preference or inconvenience; nothing is actually missing
3 = a real unmet need affecting daily life, but not health- or safety-critical;
    fine to address in the normal procurement cycle
4 = a basic staple is missing or a dietary/texture need blocks someone from
    eating what's available (e.g. no teeth and only hard food on hand)
5 = a safety- or health-critical gap (e.g. no food at all, infant formula
    completely unavailable, a medical dietary restriction with nothing safe
    to eat)
"""


class UnmetNeed(BaseModel):
    need: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_category: Literal[CATEGORY_VOCAB]


class Extraction(BaseModel):
    sentiment: Literal[SENTIMENT_VOCAB]
    urgency: int = Field(ge=1, le=5)
    categories: list[Literal[CATEGORY_VOCAB]]
    mentioned_skus: list[str]
    mentioned_terms: list[str]
    unmet_needs: list[UnmetNeed]
    detected_lang: Literal[LANG_VOCAB]
    summary_en: str


SYSTEM_PROMPT = f"""\
You extract structure from free-text feedback given by beneficiaries of a
Singapore food bank / food-rescue charity. Output must satisfy the given
schema exactly -- every enum field must be one of the listed closed-vocabulary
values, never an invented one.

sentiment: one of {SENTIMENT_VOCAB}
detected_lang: one of {LANG_VOCAB} ("other" for anything not English,
    Mandarin, Malay, or Tamil -- including mixed Singlish, which is "en")
categories: subset of {CATEGORY_VOCAB}

{URGENCY_RUBRIC}

mentioned_terms: the literal words/phrases the person used for any item they
    mention, in their own language and spelling -- do not translate, do not
    normalize, do not guess a SKU code. Just capture surface forms.
mentioned_skus: ONLY populate this if the beneficiary's text literally
    contains something that looks like an actual SKU code (e.g. "RICE-5KG").
    Almost never happens in real beneficiary text -- when in doubt, leave it
    empty. Resolving mentioned_terms to real SKUs is a separate matching step
    downstream; that is not your job here.
unmet_needs: needs implied by the text that aren't satisfied by what's on
    hand, each with a confidence and a suggested_category from the list above.
summary_en: one plain-English sentence summarizing the feedback, for a human
    reviewer who may not read the source language.
"""


# A single canned extraction for FAKE_LLM=1 (the repo-wide default). Exists so
# this service can be smoke-tested for $0 before AWS SSO is even set up --
# mirrors orchestrator's fixtures.FAKE_PLAN, not meant to represent extraction
# quality, just to exercise the DB/matcher wiring deterministically. Includes
# one clean match ("rice") and one qualifier-guard near-miss ("gluten free
# bread") so resolve_skus() has something real to chew on downstream.
FAKE_EXTRACTION = Extraction(
    sentiment="negative",
    urgency=3,
    categories=["staples", "dietary_accessibility"],
    mentioned_skus=[],
    mentioned_terms=["rice", "gluten free bread"],
    unmet_needs=[
        UnmetNeed(need="gluten-free bread", confidence=0.7, suggested_category="dietary_accessibility")
    ],
    detected_lang="en",
    summary_en="FAKE_LLM=1 canned extraction -- not a real Bedrock call.",
)


@lru_cache(maxsize=1)
def _client():
    """Bedrock client, built once. Mantle -- not the legacy InvokeModel path.

    No static keys -- boto3 resolves the SSO profile (`make aws-login`) the
    same way services/orchestrator/llm.py does. Mirrors that module's client
    construction exactly so both services share one AWS SSO setup.
    """
    from anthropic import AnthropicBedrockMantle

    return AnthropicBedrockMantle(
        aws_profile=settings.aws_profile,
        aws_region=settings.bedrock_region,
    )


def _extract_once(text: str, lang: Optional[str], previous_error: Optional[str]) -> Extraction:
    user_content = f"Beneficiary feedback (submitted lang hint: {lang or 'unknown'}):\n\n{text}"
    messages = [{"role": "user", "content": user_content}]
    if previous_error:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous output failed validation with this error. "
                    f"Fix it and re-emit the full extraction:\n\n{previous_error}"
                ),
            }
        )

    response = _client().messages.parse(
        model=settings.model_extract,
        max_tokens=settings.max_tokens_extract,
        system=SYSTEM_PROMPT,
        messages=messages,
        output_format=Extraction,
    )
    return response.parsed_output


def run_extraction(text: str, lang: Optional[str]) -> tuple[Extraction, bool]:
    """Returns (extraction, schema_valid_first_try). Raises on total failure."""
    if settings.fake_llm:
        logger.info("FAKE_LLM=1 -- returning canned extraction (no Bedrock call)")
        return FAKE_EXTRACTION, True

    try:
        extraction = _extract_once(text, lang, previous_error=None)
        return extraction, True
    except Exception as first_error:  # noqa: BLE001 -- any parse/validation failure retries once
        logger.warning("extraction failed validation on first try: %s", first_error)
        extraction = _extract_once(text, lang, previous_error=str(first_error))
        return extraction, False


_classifier = None
_classifier_load_failed = False


def _get_classifier():
    global _classifier, _classifier_load_failed
    if _classifier is not None or _classifier_load_failed:
        return _classifier
    try:
        from transformers import pipeline

        _classifier = pipeline(
            "sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english"
        )
    except Exception as e:  # noqa: BLE001 -- classifier is a second opinion, never a hard dependency
        logger.warning("HF sentiment classifier unavailable, skipping: %s", e)
        _classifier_load_failed = True
    return _classifier


@dataclass
class ClassifierResult:
    label: Optional[str]
    score: Optional[float]
    agrees: Optional[bool]  # None when not comparable (e.g. LLM said "neutral")


def run_sentiment_classifier(text: str, llm_sentiment: str) -> ClassifierResult:
    """A pretrained second opinion on sentiment only -- never ground truth.

    SST-2 is trained on English movie reviews; it will be unreliable on
    Singlish and Mandarin. Disagreement is a flag for human review, not a
    correction to the LLM's output.
    """
    classifier = _get_classifier()
    if classifier is None:
        return ClassifierResult(label=None, score=None, agrees=None)

    result = classifier(text[:512])[0]  # SST-2 truncates long input anyway
    label = result["label"]  # "POSITIVE" | "NEGATIVE"
    score = float(result["score"])

    if llm_sentiment == "neutral":
        agrees = None  # SST-2 has no neutral class -- not comparable
    elif llm_sentiment == "positive":
        agrees = label == "POSITIVE"
    else:
        agrees = label == "NEGATIVE"

    return ClassifierResult(label=label, score=score, agrees=agrees)


@dataclass
class SkuResolution:
    term: str
    matched_sku: Optional[str]
    confidence: float
    method: str
    near_sku: Optional[str]
    unmet_qualifier: Optional[str]


def resolve_skus(mentioned_terms: list[str]) -> list[SkuResolution]:
    """Matcher layers 1-3 only -- no network, no API key. Layer 4 (LLM
    adjudication) is opt-in via MATCHER_LLM_ADJUDICATION and off by default,
    since the service must be able to demo with it switched off entirely.
    """
    llm_adjudicate = None
    if settings.matcher_llm_adjudication:
        llm_adjudicate = _llm_adjudicate

    results = []
    for term in mentioned_terms:
        r = match_term(term, llm_adjudicate=llm_adjudicate)
        results.append(
            SkuResolution(
                term=term,
                matched_sku=r.matched_sku,
                confidence=r.confidence,
                method=r.method,
                near_sku=r.near_sku,
                unmet_qualifier=r.unmet_qualifier,
            )
        )
    return results


def _llm_adjudicate(term: str, sku_codes: list[str]) -> Optional[tuple[str, float]]:
    """Layer 4: only called for terms layers 1-3 couldn't resolve. Opt-in, and
    still gated on FAKE_LLM -- MATCHER_LLM_ADJUDICATION=true must not spend
    money when the repo-wide kill switch is on.
    """
    if settings.fake_llm:
        return None

    response = _client().messages.create(
        model=settings.model_extract,
        max_tokens=100,
        system=(
            "Given a beneficiary's term for a food/hygiene item and a list of SKU "
            "codes, reply with the single best-matching SKU code and a confidence "
            "0-1, or 'NONE' if nothing genuinely matches. Format: SKU_CODE|0.xx or NONE."
        ),
        messages=[{"role": "user", "content": f"Term: {term!r}\nSKU codes: {sku_codes}"}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if text == "NONE" or "|" not in text:
        return None
    sku, _, conf = text.partition("|")
    sku = sku.strip()
    try:
        confidence = float(conf.strip())
    except ValueError:
        return None
    if sku not in sku_codes:
        return None
    return sku, confidence
