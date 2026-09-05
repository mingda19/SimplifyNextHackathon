"""Golden test set for the SKU matcher. Run with:

    python -m tests.test_matcher      (from services/feedback/)

Zero false matches is the bar, not "mostly passes" -- a false match silently
erases a real unmet need downstream (see app/matcher.py module docstring), so
every case where the expected answer is None is exercised on its own line and
reported separately from ordinary failures.
"""

import unittest

from app.matcher import match_term

# (description, input text, expected matched_sku, expected near_sku, expected unmet_qualifier)
GOLDEN_CASES = [
    # --- layer 1: literal SKU code ---
    ("exact SKU code", "RICE-5KG", "RICE-5KG", None, None),
    # --- layer 2: curated alias table, multilingual ---
    ("plain English", "rice", "RICE-5KG", None, None),
    ("Mandarin", "白米", "RICE-5KG", None, None),
    ("Malay", "beras", "RICE-5KG", None, None),
    ("Tamil (transliterated)", "arisi", "RICE-5KG", None, None),
    ("sugar, Malay", "gula", "SUGAR-1KG", None, None),
    ("coffee, Mandarin", "咖啡", "INSTANT-COFFEE", None, None),
    ("chicken, Malay", "ayam", "CHICKEN-FROZEN", None, None),
    ("fish, Malay", "ikan", "FISH-FROZEN", None, None),
    ("diapers, Mandarin", "尿布", "DIAPERS-ADULT", None, None),
    ("porridge, Mandarin", "粥", "INSTANT-CEREAL", None, None),
    ("longest-alias preference", "cooking oil", "COOKING-OIL-1L", None, None),
    # --- layer 3: fuzzy / typo / voice-transcription noise ---
    ("typo", "rce please", "RICE-5KG", None, None),
    ("voice-transcription noise", "cooking oyl", "COOKING-OIL-1L", None, None),
    ("plural/typo", "noodels", "NOODLE-INST", None, None),
    # --- qualifier guard: must refuse, not silently substitute ---
    (
        "gluten free bread -> refuse, not BREAD-LOAF",
        "gluten free bread please",
        None,
        "BREAD-LOAF",
        "gluten_free",
    ),
    (
        "halal baby formula -> refuse, not MILK-POWDER",
        "need halal baby formula",
        None,
        "MILK-POWDER",
        "halal",
    ),
    (
        "low sodium noodles -> refuse, not NOODLE-INST",
        "low sodium noodles for my dad",
        None,
        "NOODLE-INST",
        "low_sodium",
    ),
    (
        "pureed vegetables -> refuse, not VEG-LEAFY",
        "pureed vegetables needed",
        None,
        "VEG-LEAFY",
        "soft_texture",
    ),
    (
        "Singlish texture complaint -> refuse, not RICE-5KG",
        "aiyo the rice damn hard leh, my mother no more teeth",
        None,
        "RICE-5KG",
        "soft_texture",
    ),
    # --- qualifier satisfied: guard must NOT block a real match ---
    ("vegetarian qualifier satisfied", "vegetarian tofu please", "TOFU", None, None),
    ("soft-texture qualifier satisfied", "soft food for elderly", "SOFT-FOOD-PACK", None, None),
    ("nut-free qualifier satisfied", "nut free beans", "CANNED-BEANS", None, None),
    # --- no SKU exists at all ---
    ("no matching SKU #1", "fresh durian please", None, None, None),
    ("no matching SKU #2", "can you get birthday cake", None, None, None),
    # --- fuzzy false positives: unrelated real words that happen to sit at
    # short edit-distance from a grocery alias (found in WS2 Phase 1 B1
    # threshold experiment, see AUDIT.md) -- these must never match ---
    ("unrelated word near 'rice'", "nice weather today", None, None, None),
    ("unrelated word near 'fish'", "I wish you well", None, None, None),
    ("unrelated word near 'fish'", "wash the dish please", None, None, None),
    ("unrelated word near 'eggs'", "carry the legs", None, None, None),
    ("unrelated word near 'noodles'", "toy poodles are cute", None, None, None),
    ("unrelated word near 'coffee'", "a piece of toffee", None, None, None),
    ("unrelated word near 'diapers'", "car windscreen wipers", None, None, None),
    # --- qualifier guard: paraphrases/languages the fixed phrase list missed
    # (found in WS2 Phase 1 B2 probe, see AUDIT.md) ---
    (
        "no MSG -> refuse, not CHICKEN-FROZEN",
        "no msg chicken please",
        None,
        "CHICKEN-FROZEN",
        "msg_free",
    ),
    (
        "soft texture (paraphrase) -> refuse, not INSTANT-CEREAL",
        "soft texture porridge please",
        None,
        "INSTANT-CEREAL",
        "soft_texture",
    ),
    (
        "low sugar (paraphrase) -> refuse, not INSTANT-COFFEE",
        "low sugar coffee please",
        None,
        "INSTANT-COFFEE",
        "sugar_free",
    ),
    (
        "no sugar, Mandarin -> refuse, not MILK-POWDER",
        "无糖奶粉",
        None,
        "MILK-POWDER",
        "sugar_free",
    ),
    (
        "no sugar, Malay -> refuse, not MILK-POWDER",
        "tanpa gula susu tepung",
        None,
        "MILK-POWDER",
        "sugar_free",
    ),
]


class TestMatcherGolden(unittest.TestCase):
    def test_golden_cases(self):
        false_matches = []
        failures = []

        for description, text, expected_sku, expected_near, expected_qualifier in GOLDEN_CASES:
            result = match_term(text)

            if expected_sku is None and result.matched_sku is not None:
                false_matches.append(
                    f"FALSE MATCH  [{description}]  {text!r} -> {result.matched_sku} "
                    f"(expected None, method={result.method}, confidence={result.confidence:.2f})"
                )
                continue

            if result.matched_sku != expected_sku:
                failures.append(
                    f"[{description}]  {text!r} -> matched_sku={result.matched_sku!r}, "
                    f"expected {expected_sku!r}"
                )
                continue

            if expected_near is not None and result.near_sku != expected_near:
                failures.append(
                    f"[{description}]  {text!r} -> near_sku={result.near_sku!r}, "
                    f"expected {expected_near!r}"
                )

            if expected_qualifier is not None and result.unmet_qualifier != expected_qualifier:
                failures.append(
                    f"[{description}]  {text!r} -> unmet_qualifier={result.unmet_qualifier!r}, "
                    f"expected {expected_qualifier!r}"
                )

        if false_matches:
            print("\n--- FALSE MATCHES (zero tolerance) ---")
            for line in false_matches:
                print(line)

        if failures:
            print("\n--- OTHER FAILURES ---")
            for line in failures:
                print(line)

        self.assertEqual(false_matches, [], "false matches must be zero")
        self.assertEqual(failures, [], "golden case mismatches")


if __name__ == "__main__":
    unittest.main()
