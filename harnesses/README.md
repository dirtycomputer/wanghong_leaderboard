# Harnesses

Every runnable harness lives in one directory:

```text
harnesses/<name>/
  harness.yaml
  run.sh
```

`run.sh` performs the task. It reads `/task/task.yaml` and must write the five
required output files under `/output`.

The runner mounts only approved internal services. Use `MODEL_API_BASE` for
model calls and `SEARCH_API_BASE` for restricted pre-cutoff search when the
harness enables it.
