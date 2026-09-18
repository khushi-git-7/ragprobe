"""Enable ``python -m ragprobe`` as well as the installed ``ragprobe`` script.

Useful in CI and for contributors who have not run ``pip install -e .`` yet.
"""

from ragprobe.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
