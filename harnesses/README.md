# Harnesses

Every runnable harness lives in one directory:

```text
harnesses/<name>/
  harness.yaml
  run.sh
```

`run.sh` performs the task. In local testing, call it directly with:

```bash
bash harnesses/<name>/run.sh --task tasks/kakeya3d_discovery.yaml --output runs/<name>/output
```

The official Docker runner path is not fully wired through yet.

Restricted search currently means two explicit tools:

```text
openalex_search.py
exa_search.py
```
