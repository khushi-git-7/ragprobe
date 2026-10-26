"""The reference data RAGProbe ships: golden set, corpus, attacks, benign set, benchmark.

It lives inside the package so that ``pip install ragprobe`` is enough to run
``ragprobe demo`` or a scan from any directory - an installed tool that cannot find
its own data is not installed. Paths are resolved by
:func:`ragprobe.resources.resolve_data`: a copy in your working directory wins, so
you can take these files, edit them and keep using the plain commands.
"""
