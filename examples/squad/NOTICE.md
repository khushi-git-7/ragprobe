# Source and license

The documents under `corpus/` and the questions in `golden_set.yaml` are derived from
the SQuAD 2.0 dev split (Rajpurkar, Jia and Liang, 2018), obtained from
https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json and redistributed under the Creative Commons Attribution-ShareAlike 4.0
license. Each article became one markdown file with one section per paragraph;
questions were sampled by `ragprobe import squad` (seed 7, limit 120,
unanswerable ratio 0.25).
