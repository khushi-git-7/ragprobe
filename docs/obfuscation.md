# Obfuscated injections and normalization

A keyword or heuristic detector matches the literal text, so an attacker hides the
trigger words while keeping them readable to the model:

- **zero-width** — insert invisible characters between letters (`i​g​n​o​r​e`).
- **homoglyph** — swap letters for look-alikes from another alphabet (Cyrillic
  `о` for Latin `o`).
- **spaced-out** — stretch the words (`i g n o r e`).
- **leetspeak** — swap letters for digits (`1gn0r3`). The normalizer reads a word as leetspeak only when it mixes letters and digits and has no digit that is not a letter swap, so `2024` and `base64` are left alone.
- **html-comment / html-hidden / markdown-alt** — bury the instruction in markup
  the model still reads.

## The gap, and the fix

Run `ragprobe security obfuscation`:

| Obfuscation | Recall (raw) | Recall (normalized) |
|---|--:|--:|
| none | 83% | 83% |
| zero-width | 0% | 83% |
| homoglyph | 0% | 83% |
| spaced-out | 0% | 83% |
| leetspeak | 0% | 83% |
| html-comment | 83% | 83% |
| html-hidden | 83% | 83% |
| markdown-alt | 83% | 83% |

Tricks that keep the words intact (HTML/markdown) are caught even raw. Tricks that
mangle the characters (zero-width, look-alike glyphs, spacing, leetspeak) take the detector to
**0%** — until the text is normalized first, which restores it to the baseline.

`normalize()` does Unicode (NFKC) folding, drops format characters, maps common
confusable glyphs back to ASCII, reveals HTML-commented and tag-hidden text, and
rejoins single-letter runs — and it leaves ordinary sentences untouched
(`"I am a big fan of cats"` is unchanged). `NormalizingDetector` wraps any detector
to apply this as a deployable pre-filter, so the detector benchmark's numbers hold
up under adversarial obfuscation, not just clean inputs.

The default `detector` defence (and so the `layered` preset) now screens through this normalizer, and flags text if either the raw or the cleaned reading is flagged, so cleaning can never make it blinder.
