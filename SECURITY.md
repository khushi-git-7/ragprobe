# Security policy

## Responsible use

RAGProbe is a **defensive** tool. Its attack corpus exists so that you can measure
how your own LLM, RAG or agent application holds up against the OWASP Top 10 for
LLM Applications, and whether your defences work. The published techniques are
generic and already public.

Only run RAGProbe against:

- systems you own, or
- systems you have explicit, written authorisation to test, or
- RAGProbe's own simulated and local victims (the default).

Do **not** point it at third-party chatbots, government services, or anyone's
production system without authorisation. The project will not help with that.

## Reporting a vulnerability

If you find a security issue **in RAGProbe itself** (for example, a way the tool
could be made to execute untrusted input, leak a key, or write outside its output
paths), please report it privately rather than opening a public issue:

- open a [GitHub security advisory](https://github.com/khushi-git-7/ragprobe/security/advisories/new), or
- email the maintainer (see the commit history for the address).

Please include what you did, what you expected, and what happened. We aim to
acknowledge a report within a week.

## Scope

In scope: the RAGProbe code, its CLI, its report generators, and its CI workflow.

Out of scope: the behaviour of the third-party models RAGProbe can call (report
those to the model provider), and findings produced *by* RAGProbe about your own
application (those are for you to fix).

## Handling of secrets

RAGProbe reads API keys only from environment variables, never from the repo, and
never logs or commits them. Cached model responses contain prompts and replies,
not keys. If you commit a cache, review it first.
