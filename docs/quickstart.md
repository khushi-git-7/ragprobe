# Quickstart: your first security scan in five minutes

Everything below is free and offline. No API key is needed until you choose to
test a live model.

## 1. Install

```bash
git clone https://github.com/khushi-git-7/ragprobe.git
cd ragprobe
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
ragprobe doctor                                 # checks the install, data and keys
```

`doctor` prints a line per check and tells you what to fix. Missing API keys are
only warnings; they matter for live-model runs, not for anything on this page.

## 2. Watch the whole story (one command)

```bash
ragprobe demo
```

This walks through a fictional, deliberately vulnerable app, **Acme Helpdesk**: it
scans the app as it ships (grade **F**), adds defences step by step, rescans, and
ends at grade **A**, also checking that the defence is not just blocking everyone.
Every number comes from a real run. The victim is a simulated always-obey model, so
this is a worst-case drill that exercises the harness and the code-level defences,
not a measurement of any real model.

## 3. Scan with your own settings

```bash
ragprobe security run --defenses none,layered --benign --html reports/security.html
```

Open `reports/security.html`: an A-F grade per OWASP risk, attack-success per
defence with 95% intervals, and the false-block rate beside it.

## 4. Go further

| I want to... | Run |
|---|---|
| gate CI on security | `ragprobe security run --min-reduction 0.5` |
| test tool/MCP poisoning | `ragprobe security mcp` |
| test multi-turn attacks | `ragprobe security multiturn` |
| see how obfuscation evades a detector | `ragprobe security obfuscation` |
| run the frozen benchmark | `ragprobe bench run --split test` |
| rank models (needs free API keys) | `ragprobe bench leaderboard --cache` |

Only point RAGProbe at systems you own or are authorised to test; see
[SECURITY.md](../SECURITY.md). The method behind the numbers is in
[methodology.md](methodology.md).
