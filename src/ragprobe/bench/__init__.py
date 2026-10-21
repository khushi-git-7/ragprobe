"""RAGProbe Bench - a frozen, versioned, tagged attack benchmark.

The security suite needs a corpus to run; this package builds a *citable* one:
every item carries an id, an OWASP category, a technique tag, a language, and the
source and licence it came from, split into train / dev / test so detectors are
tuned on dev and reported only on test.

Two kinds of item live in one catalogue:

- ``attack`` - a verifiable, canary-structured attack that runs through the
  security suite and whose success is checked by an oracle (no human judgement).
- ``probe``  - a labelled injection / benign string from an external dataset,
  used to benchmark detectors and measure false positives. Not self-verifying.

Keeping both in one file, tagged by ``kind``, lets the datasheet report honest
totals while the runner selects only what it can actually score.
"""

from ragprobe.bench.schema import (  # noqa: F401
    LANGUAGES,
    LICENCES,
    SOURCES,
    SPLITS,
    TECHNIQUES,
    BenchItem,
    to_attack,
)
