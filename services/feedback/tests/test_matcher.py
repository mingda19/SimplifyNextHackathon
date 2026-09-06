"""Golden cases for the SKU matcher.

UPDATED 6 Sep: expectations now use the REAL inventory catalogue codes from
workstream 1 (GET /inventory), not the old 20-SKU stub in app/skus.py. Of the
stub's codes only RICE-5KG and SUGAR-1KG ever existed in the seeded inventory,
so every other expectation here was asserting a SKU that does not exist.

BREAD-LOAF and SOFT-FOOD-PACK have NO real equivalent — the charity stocks
neither bread nor a soft/pureed meal pack. Those cases now assert an unmatched
result, which is the correct and more valuable answer: a need nobody stocks for.
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
    ("coffee, Mandarin", "咖啡", "COFFEE-500G", None, None),
    ("chicken, Malay", "ayam", "CHICKEN-FROZEN-1KG", None, None),
    ("fish, Malay", "ikan", "FISH-FROZEN-1KG", None, None),
    ("diapers, Mandarin", "尿布", "DIAPERS-M-40PK", None, None),
    # 粥 is rice congee, a prepared dish the charity does not stock. It used to
    # resolve to OATS-1KG; the LLM judge flagged that as a wrong match in 4 of
    # 16 test-set failures, so it is now a documented catalogue gap.
    ("porridge, Mandarin -> catalogue gap", "粥", None, None, None),
    ("longest-alias preference", "cooking oil", "OIL-2L", None, None),
    # --- layer 3: fuzzy / typo / voice-transcription noise ---
    ("typo", "rce please", "RICE-5KG", None, None),
    ("voice-transcription noise", "cooking oyl", "OIL-2L", None, None),
    ("plural/typo", "noodels", "NOODLES-1KG", None, None),
    # --- qualifier guard: must refuse, not silently substitute ---
    (
        "gluten free bread -> no bread SKU exists at all",
        "gluten free bread please",
        None,
        None,          # nothing to be near — the catalogue has no bread
        None,
    ),
    (
        "halal baby formula -> refuse, not MILK-POWDER",
        "need halal baby formula",
        None,
        "INFANT-FORMULA-900G",
        "halal",
    ),
    (
        "low sodium noodles -> refuse, not NOODLE-INST",
        "low sodium noodles for my dad",
        None,
        "NOODLES-1KG",
        "low_sodium",
    ),
    (
        "pureed vegetables -> refuse, not VEG-LEAFY",
        "pureed vegetables needed",
        None,
        "VEGETABLES-MIXED-1KG",
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
    ("vegetarian qualifier satisfied", "vegetarian tofu please", "TOFU-300G", None, None),
    # No soft/pureed meal SKU exists — this is a genuine catalogue gap and the
    # highest-signal output of the feedback loop, not a matcher failure.
    ("soft food is a catalogue gap", "soft food for elderly", None, None, None),
    ("nut-free qualifier satisfied", "nut free beans", "BEANS-CANNED-400G", None, None),
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
        "CHICKEN-FROZEN-1KG",
        "msg_free",
    ),
    (
        # "porridge" now means rice congee (a prepared dish the charity does
        # not stock), so this refuses at layer 0 rather than on soft_texture.
        # Either way it is correctly refused, which is what the invariant is.
        "soft texture porridge -> refuse as a catalogue gap",
        "soft texture porridge please",
        None,
        None,
        None,
    ),
    (
        "low sugar (paraphrase) -> refuse, not INSTANT-COFFEE",
        "low sugar coffee please",
        None,
        "COFFEE-500G",
        "sugar_free",
    ),
    (
        # Same as the Malay case: 奶粉 is generic powdered milk, a catalogue
        # gap, so it is refused at layer 0 before the sugar-free check.
        "no sugar + Mandarin generic milk powder -> refuse as a catalogue gap",
        "无糖奶粉",
        None,
        None,
        None,
    ),
    (
        # Refused, but for a stronger reason than the sugar-free qualifier:
        # generic powdered milk is not in the catalogue at all, so layer 0
        # short-circuits before qualifier detection runs.
        "no sugar + generic milk powder -> refuse as a catalogue gap",
        "tanpa gula susu tepung",
        None,
        None,
        None,
    ),
    # --- Tamil, native script (found in WS2 Phase 1 A3/C2: the golden set's
    # only prior Tamil case was romanized "arisi"; the alias word-boundary
    # regex silently fails to match native Tamil Unicode script at all --
    # see AUDIT.md C2) ---
    ("Tamil, native script, rice", "அரிசி", "RICE-5KG", None, None),
    ("Tamil, native script, coffee", "காபி", "COFFEE-500G", None, None),
    (
        "Tamil, native script, in a sentence",
        "எனக்கு அரிசி வேணும்",
        "RICE-5KG",
        None,
        None,
    ),
    # --- qualifier guard false-trigger: substring collision, not a real
    # qualifier mention (found in WS2 Phase 1 Loop B, see AUDIT.md) ---
    (
        "'no msg' substring inside 'no msgs' (text messages) must not block",
        "sorry no msgs came through, can I get some chicken",
        "CHICKEN-FROZEN-1KG",
        None,
        None,
    ),
    # --- Phase 5a: Tamil diabetes term collides with the sugar alias (LIVE
    # BUG). சர்க்கரை நோய் literally means "sugar disease" (diabetes); the
    # bare சர்க்கரை alias inside it was matching SUGAR-1KG at 0.93 confidence
    # -- a beneficiary saying "I have diabetes" was matched to a bag of sugar.
    # Fixed as a SUGAR_FREE qualifier trigger, not by deleting the சர்க்கரை
    # alias -- legitimate Tamil sugar requests must keep working (see the
    # second case below). ---
    (
        "Tamil 'diabetes' (sugar disease) -> refuse, not SUGAR-1KG",
        "சர்க்கரை நோய்",
        None,
        "SUGAR-1KG",
        "sugar_free",
    ),
    (
        "Tamil, legitimate sugar request must still work after the 5a fix",
        "சர்க்கரை வேணும்",
        "SUGAR-1KG",
        None,
        None,
    ),
    # --- Phase 5b: "milo" (a malted drink, not milk) false-matched MILK-UHT-1L
    # at fuzzy 0.75. Not one of the four residual fuzzy false positives already
    # documented above -- a distinct catalogue gap (no malted-drink SKU exists). ---
    (
        "milo -> catalogue gap, not MILK-UHT-1L",
        "milo",
        None,
        None,
        None,
    ),
    # --- Phase 5c: repo owner's decision -- generic "drinks" requests resolve
    # to bottled water for now (not a catalogue gap), since the charity does
    # stock something drinkable even though nobody asked for water
    # specifically. Revisit if/when a wider beverage catalogue exists;
    # KNOWN_GAPS + the unmet-needs aggregation is how a *more specific*
    # unstocked drink (e.g. "milo", "juice") still gets surfaced instead of
    # silently matching water too. ---
    ("generic 'drinks' -> bottled water (repo owner decision)", "drinks", "WATER-1-5L", None, None),
    ("generic 'beverages' -> bottled water (repo owner decision)", "beverages", "WATER-1-5L", None, None),
    # "drink" is NOT its own alias key -- it fuzzy-matched "durian" at 0.73
    # when it was one (false match on "fresh durian please"). It still
    # correctly resolves via the fuzzy layer against the surviving "drinks"
    # alias (0.91, singular/plural), which does NOT collide with "durian"
    # (0.67, below threshold) -- this is the desired outcome, not a residual
    # false positive.
    ("generic 'drink' (singular) -> water via fuzzy against 'drinks', not its own alias",
     "drink", "WATER-1-5L", None, None),
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
