"""Security testing: prompt injection, poisoned documents and agent hijacking.

RAGProbe's quality suite asks "is the answer right?". This package asks "can the
system be made to do the attacker's bidding, and does the defence stop it?" - with
the same principles: deterministic offline by default, checkable ground truth
instead of an LLM's opinion, and a regression gate that fails CI when a change
makes the system easier to attack.

See docs/security.md for the threat model and the methodology.
"""
