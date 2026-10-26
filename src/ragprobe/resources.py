"""Find the data RAGProbe ships, wherever it was installed.

The golden set, the document corpus, the attack corpus, the benign set and the
frozen benchmark all travel inside the package (``ragprobe/datasets``), so the
tool works straight after ``pip install`` from any directory. The commands still
*name* those files the way the repository lays them out
(``datasets/security/attacks.yaml``), because that is what a user reads in the
docs and what ``--attacks`` takes.

:func:`resolve_data` bridges the two, with one rule:

1. the path you asked for, if it exists - your own copy always wins, so you can
   take the shipped files, edit them and keep typing the plain commands;
2. otherwise the copy inside the installed package;
3. otherwise the path you asked for, unchanged, so the error message that follows
   names the file *you* meant and not one of ours.

Nothing here reads a file or needs a dependency: it only decides on a path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

#: The shipped data directory inside the installed package.
BUNDLED = Path(__file__).resolve().parent / "datasets"

#: The prefix the repository (and every example in the docs) puts in front of it.
PREFIX = "datasets"


def bundled_path(relative: Union[str, Path]) -> Path:
    """The shipped copy of ``relative``, e.g. ``security/attacks.yaml``."""
    return BUNDLED / Path(relative)


def resolve_data(path_like: Union[str, Path]) -> Path:
    """The path to read for a shipped data file: yours if present, else ours."""
    path = Path(path_like)
    if path.exists():
        return path
    parts = path.parts
    # "datasets/security/attacks.yaml" and "security/attacks.yaml" both mean ours
    tail = Path(*parts[1:]) if parts and parts[0] == PREFIX else path
    if not tail.parts:
        return path
    bundled = bundled_path(tail)
    return bundled if bundled.exists() else path


def resolve_under(base_dir: Union[str, Path, None], relative: Union[str, Path]) -> Path:
    """A data path written as "relative to the project root", resolved for real.

    The project's own copy under ``base_dir`` wins; otherwise the shipped copy. This
    is the form the commands use, because ``--root`` lets you point a run at another
    checkout, and a pip-installed user has no checkout at all.

    An absolute ``relative`` is returned untouched: a path somebody typed in full is
    never quietly swapped for one of ours.
    """
    path = Path(relative)
    if path.is_absolute():
        return path
    joined = Path(base_dir) / path if base_dir is not None else path
    if joined.exists():
        return joined
    bundled = resolve_data(path)
    return bundled if bundled.exists() else joined


def is_bundled(path_like: Union[str, Path]) -> bool:
    """True if this path is the shipped copy rather than one of the user's."""
    try:
        return Path(path_like).resolve().is_relative_to(BUNDLED)
    except OSError:  # pragma: no cover - a path the OS will not resolve
        return False
