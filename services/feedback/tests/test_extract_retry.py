"""Phase 4: run_extraction's retry must only fire for genuine schema/parse
failures, not transport/auth/rate-limit errors.

app/extract.py's `except Exception` currently retries on EVERYTHING,
including a 429 or an expired token -- sending "your previous output failed
validation, fix it" to Claude in response to an error that has nothing to do
with validation. Two real consequences: a transport error costs a second
wasted Bedrock call before finally propagating (or worse, "succeeding" on
retry and being silently miscounted), and `schema_valid_first_try` gets set
False for a transport hiccup that has nothing to do with schema quality --
which is exactly what Phase 2's schema_pass_rate metric depends on being
accurate. See AUDIT.md / the execution plan's Phase 4.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx2
import pydantic

from app import extract


def _real_validation_error() -> pydantic.ValidationError:
    """A genuine ValidationError, not a hand-constructed stand-in -- triggered
    by actually violating Extraction's schema (bad enum value)."""
    try:
        extract.Extraction(
            sentiment="angry",  # not in SENTIMENT_VOCAB
            urgency=3,
            categories=[],
            mentioned_skus=[],
            mentioned_terms=[],
            unmet_needs=[],
            detected_lang="en",
            summary_en="x",
        )
    except pydantic.ValidationError as e:
        return e
    raise AssertionError("expected Extraction(...) to raise ValidationError")


def _real_rate_limit_error():
    import anthropic

    resp = httpx2.Response(429, request=httpx2.Request("POST", "https://example.com"))
    return anthropic.RateLimitError("Too many requests, please wait before trying again.",
                                     response=resp, body=None)


class TestRunExtractionRetry(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(extract.settings, "fake_llm", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_validation_error_retries_once_with_error_in_message(self):
        validation_error = _real_validation_error()
        good = extract.FAKE_EXTRACTION

        with patch.object(extract, "_extract_once",
                           side_effect=[validation_error, good]) as mock_once:
            result, schema_valid_first_try = extract.run_extraction("some text", "en")

        self.assertEqual(mock_once.call_count, 2,
                          "a validation failure must retry exactly once")
        self.assertEqual(result, good)
        self.assertFalse(schema_valid_first_try)

        _, second_call_kwargs = mock_once.call_args_list[1]
        previous_error = second_call_kwargs.get("previous_error")
        self.assertIsNotNone(previous_error, "retry must pass the validation error back")
        self.assertIn("validation", str(previous_error).lower())

    def test_transport_error_does_not_retry(self):
        import anthropic

        transport_error = _real_rate_limit_error()

        with patch.object(extract, "_extract_once",
                           side_effect=transport_error) as mock_once:
            with self.assertRaises(anthropic.RateLimitError):
                extract.run_extraction("some text", "en")

        self.assertEqual(mock_once.call_count, 1,
                          "a transport/rate-limit error must NOT retry -- "
                          "it should propagate immediately, not spend a second "
                          "Bedrock call on a 'fix your validation error' retry "
                          "that cannot possibly help")


if __name__ == "__main__":
    unittest.main()
