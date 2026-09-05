# Failure Log

Append-only. Each entry: date, phase, what was hunted, findings, verdict per item, commit hashes.

---

## 2026-09-05 — Phase 1 (fixes to what Phase 0's audit found)

Hunted: `app/matcher.py`, `app/skus.py`, and the golden test set, i.e. everything touched by the B1/B2/A1/A3/C2 fixes in this phase (commits `ab1cfb0`, `b9dc4e8`, `58d25ba`). Went through the 8 categories; most came back NONE because this phase's changes are confined to pure string-matching functions with no I/O, no shared state, and no concurrency surface.

1. **INPUT** — tested empty string, whitespace-only, and a mixed-script code-switched term (`"rice arisi"`). All handled correctly (empty → `None`/`"none"`, mixed-script → resolves to the shared SKU with no conflict). No bug.
2. **CONCURRENCY** — NONE. `match_term` is a pure function; no shared mutable state, no caching, nothing to race.
3. **DEPENDENCY** — NONE. Nothing in this phase's changes touches Bedrock, Postgres, or any network call.
4. **STATE** — NONE. No persistence in the touched files.
5. **CONTRACT** — NONE. No extraction-contract field renamed. The new `msg_free` qualifier value is additive to `sku_matches.unmet_qualifier`, which is free `TEXT` (no `CHECK` constraint), so it's non-breaking.
6. **MODEL** — checked whether adding `MSG_FREE` (a qualifier tag with zero SKUs marked as satisfying it) causes unintended always-block behavior. It does, by design (reports a near-miss instead of a false match), and that's the intended behavior — already covered by the B2 golden case.
7. **HUMAN** — checked Unicode normalization (NFC vs NFD) for the newly-added native Tamil aliases, since different input methods can encode the same visible character differently. For the specific words added, Python's `unicodedata.normalize` produces identical NFC/NFD forms (no combining-mark decomposition for these characters) — not a live risk for this data, though it could recur if more Tamil words are added later that do decompose. Logged as a watch-item, not fixed (nothing to fix — it isn't currently broken).
8. **DEMO DAY** — checked whether logging raw Tamil/Mandarin beneficiary text on a non-UTF-8 Windows console (the actual default on a fresh `cmd.exe`/legacy PowerShell session) crashes `extract_and_store` and wrongly marks a successful extraction as `'failed'`. Reproduced the underlying `UnicodeEncodeError` on a narrow-codepage stream, but Python's `logging` module catches it internally in `Handler.handleError()` and does not re-raise — it prints `--- Logging error ---` to stderr and continues. **Already handled**, by the standard library, not by anything in this codebase.

### Top 5 (by likelihood × blast radius), ranked

| # | Finding | Verdict | Commit |
|---|---|---|---|
| 1 | `_detect_qualifiers` used a plain substring check (no word boundaries) for Latin-script phrases; the new `"no msg"` pattern (from the B2 fix) false-triggered on `"no msgs"` (text messages), wrongly blocking a legitimate item match | **FIXED** | `173aa72` |
| 2 | Console-encoding crash on Tamil/Mandarin log text mislabeling a successful extraction as `'failed'` | ALREADY HANDLED (stdlib `logging`) | — |
| 3 | NFC/NFD normalization mismatch for native-script Tamil aliases | ALREADY HANDLED for current data (no decomposition exists for the added words); watch-item if more Tamil words are added later | — |
| 4 | Empty/whitespace-only input to `match_term` | ALREADY HANDLED (returns `None`/`"none"` cleanly) | — |
| 5 | Mixed-script code-switched single term (e.g. `"rice arisi"`) | ALREADY HANDLED (resolves correctly, no conflict for this case) | — |

Only item 1 required a code change. Items 2-5 were verified with a real test/reproduction and passed — kept as evidence, no code touched.

### Carried forward from the Phase 1 fix commits (not re-litigated here, already disclosed)

- **Alias longest-match tiebreak is dict-order-dependent**, not context-aware, when two different items' aliases tie in length within one sentence. Found while designing the B2 Mandarin/Malay test cases; worked around, not fixed. Needs its own pass — see `AUDIT.md` Phase 1 update.
- **Fuzzy layer (layer 3) doesn't work for Tamil script** — `_match_fuzzy` only tokenizes `[a-z]+`. C2 fixed the alias (layer 2) gap; typo/voice-noise tolerance for Tamil remains unsupported.
- **4 residual fuzzy false-positives** ("race"→rice, "bead"→bread, "beams"→rice, "milk flower"→milk powder) survive the B1 first-character gate; documented in `matcher.py`'s `_match_fuzzy` comment and the B1 commit message (`ab1cfb0`). No single ratio threshold closes these without costing real-typo recall (shown by the threshold scan in that commit). Not re-tested here since they were already evidenced and disclosed at the time of the B1 fix, not newly discovered by this Loop B pass.
