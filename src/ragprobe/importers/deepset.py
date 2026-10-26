"""Import the deepset/prompt-injections dataset for detector benchmarking.

deepset/prompt-injections (Apache-2.0, https://huggingface.co/datasets/deepset/prompt-injections)
is 662 short texts labelled 1 (a prompt-injection attempt) or 0 (an ordinary
request), split 546 train / 116 test. It is small, but it is *independent*: none of
RAGProbe's own attacks or detector rules were written from it, which is the point.
A detector is tuned on the train split only and its numbers are reported on the
test split only, so the headline result is never measured on data it was fitted to.

Rows are fetched from the Hugging Face datasets-server JSON API with the standard
library, so no ``datasets``/``pyarrow`` install is needed.

Usage::

    ragprobe security import-deepset --out datasets/security/deepset
"""

from __future__ import annotations

from ragprobe.errors import RagprobeError
from ragprobe.resources import resolve_data

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

DATASET = "deepset/prompt-injections"
ROWS_URL = "https://datasets-server.huggingface.co/rows"
SPLITS = ("train", "test")
PAGE = 100

NOTICE = """# Source and license

`train.jsonl` and `test.jsonl` are the train and test splits of
[deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections),
redistributed unchanged (one JSON object per row: `text`, `label`) under the Apache
License 2.0. `label` 1 means the text is a prompt-injection attempt, 0 means it is an
ordinary request. Fetched with `ragprobe security import-deepset`.

The dataset is used only to measure detectors. RAGProbe's heuristic detector is
tuned on `train.jsonl`; every number in the README comes from `test.jsonl`.
"""


class DeepsetImportError(RagprobeError, ValueError):
    """The API answered in an unexpected shape."""


def _get_json(url: str) -> Dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ragprobe"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_split(split: str, get_json: Callable[[str], Dict] = _get_json) -> List[Dict]:
    """Every row of one split, in dataset order."""
    rows: List[Dict] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {"dataset": DATASET, "config": "default", "split": split,
             "offset": offset, "length": PAGE}
        )
        payload = get_json(f"{ROWS_URL}?{query}")
        page = payload.get("rows")
        if not isinstance(page, list):
            raise DeepsetImportError(f"unexpected response for {split}: {str(payload)[:200]}")
        for item in page:
            row = item.get("row", {})
            text, label = row.get("text"), row.get("label")
            if not isinstance(text, str) or label not in (0, 1):
                raise DeepsetImportError(f"bad row in {split}: {str(row)[:200]}")
            rows.append({"text": text, "label": int(label)})
        total = payload.get("num_rows_total", len(rows))
        offset += PAGE
        if not page or offset >= total:
            return rows


def write_splits(out: Path, splits: Dict[str, List[Dict]]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with (out / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "NOTICE.md").write_text(NOTICE, encoding="utf-8")
    return out


def load_split(path: Path) -> List[Dict]:
    """Read a ``{"text", "label"}`` JSONL file written by :func:`write_splits`."""
    rows = []
    with resolve_data(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row.get("text"), str) or row.get("label") not in (0, 1):
                raise DeepsetImportError(f"{path}:{number}: expected text and a 0/1 label")
            rows.append(row)
    return rows


def import_deepset(out: Path, get_json: Optional[Callable[[str], Dict]] = None) -> Dict[str, int]:
    fetch = get_json or _get_json
    splits = {split: fetch_split(split, fetch) for split in SPLITS}
    write_splits(out, splits)
    return {split: len(rows) for split, rows in splits.items()}
