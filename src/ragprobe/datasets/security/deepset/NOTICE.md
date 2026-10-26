# Source and license

`train.jsonl` and `test.jsonl` are the train and test splits of
[deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections),
redistributed unchanged (one JSON object per row: `text`, `label`) under the Apache
License 2.0. `label` 1 means the text is a prompt-injection attempt, 0 means it is an
ordinary request. Fetched with `ragprobe security import-deepset`.

The dataset is used only to measure detectors. RAGProbe's heuristic detector is
tuned on `train.jsonl`; every number in the README comes from `test.jsonl`.
