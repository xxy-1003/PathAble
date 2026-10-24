# Measured data package

`--mode measured` accepts only an explicit `--data-dir`; it never reads the
bundled `fixtures/` directory. Keep participant footage and raw logs outside
Git. Obtain consent and apply the project's privacy rules before sharing them.

Create `measured_data/manifest.json` with this structure (values shown are
**placeholders**, not measured results):

```json
{
  "schema_version": 1,
  "data_origin": "PHYSICAL_MEASURED",
  "collection": {
    "collection_id": "REPLACE_WITH_UNIQUE_REAL_SESSION_ID",
    "site": "REPLACE_WITH_ACTUAL_SITE",
    "recorded_by": "REPLACE_WITH_RECORDER_NAME",
    "recorded_at_utc": "REPLACE_WITH_ACTUAL_UTC_TIMESTAMP"
  },
  "evidence_review": {
    "reviewed_by": "REPLACE_WITH_ACTUAL_REVIEWER",
    "reviewed_at_utc": "REPLACE_WITH_ACTUAL_UTC_TIMESTAMP",
    "source_files_checked": true,
    "labels_checked": true,
    "benchmark_runs_checked": true
  },
  "datasets": {
    "detection": {"file": "detection.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/detection_log.csv", "sha256": "REPLACE_WITH_SHA256"}]},
    "scenarios": {"file": "scenarios.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/decision_trace.jsonl", "sha256": "REPLACE_WITH_SHA256"}]},
    "routes": {"file": "routes.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/route_trial_log.csv", "sha256": "REPLACE_WITH_SHA256"}]},
    "latency": {"file": "latency.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/timing_log.csv", "sha256": "REPLACE_WITH_SHA256"}]},
    "cloud": {"file": "cloud.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/cloud_event_log.jsonl", "sha256": "REPLACE_WITH_SHA256"}]},
    "cool": {"file": "cool.json", "sha256": "REPLACE_WITH_SHA256", "evidence": [{"file": "raw/benchmark_run.json", "sha256": "REPLACE_WITH_SHA256"}]}
  }
}
```

Each summary JSON must contain:

```json
"metadata": {
  "data_origin": "PHYSICAL_MEASURED",
  "collection_id": "SAME_ID_AS_MANIFEST"
}
```

The payload field after `metadata` is `samples` for detection,
`trials` for scenarios, `runs` for routes, `samples_ms` for latency,
`sequences` for cloud, and `configurations` for COOL. Their row formats are
described by `metrics.py` and the scenario/trace protocol documents. The gate
requires at least 80 scenario trials, 20 route runs, 30 cloud sequences, and
COOL plus stock Graviton records with at least 300 frame timings each. The
two Graviton records must have `provider` values `cool` and `stock`, matching
`instance_type`, `input_manifest_sha256`, and `model_sha256`, plus a positive
`total_time_s` and verified positive `hourly_rate`. The optional x86
configuration is reported only if collected.

For each actual file, compute its hash with PowerShell and copy the result into
the manifest:

```powershell
(Get-FileHash -Algorithm SHA256 measured_data/detection.json).Hash.ToLower()
```

After recording, a named reviewer must check that the original footage/logs
match the summary rows, labels, dates, and hardware, then complete the
`evidence_review` fields truthfully. Hash checks and a review declaration cannot
independently prove that a file came from a real physical trial. Each dataset
needs its own nonempty original source log or recording. The COOL summary must also be reconciled
with Person 4's raw `run.json` files and comparison checks before speedup or cost
numbers are used in the submission.
