# PathAble v3: Evaluation and Submission Evidence (Person 5)

This directory contains the independent evaluation framework, metric calculation engine, scenario protocols, report outline, and demo video storyboard for PathAble v3 (Proposal Section 12).

---

## Directory Structure

```
production/v3/evaluation/
├── README.md                          # Package overview and usage guide
├── scenarios.md                       # The 8 evaluation scenarios (80 trials) & ground-truth schema
├── trace_format.md                    # Decision trace schema (Section 11)
├── baseline_ablation_protocol.md      # Baseline (static map) & ablation (no active perception) protocols
├── failure_case_checklist.md          # Failure-case categorization & audit checklist
├── report_outline.md                  # Comprehensive technical report outline for Devpost submission
├── demo_video_storyboard.md           # 5-minute competition video script & visual storyboard
├── evidence_needed.md                 # Detailed list of evidence needed from teammates & corridor trials
├── metrics.py                         # Core metrics calculation engine (detection, decisions, routes, latency, COOL)
├── run_evaluation_pipeline.py         # Evaluation pipeline CLI runner
├── test_metrics.py                    # Unit tests for metric calculations
├── evaluation_summary_report.md       # Submission placeholder until measured evidence exists
├── measured_inputs.py                  # Measured-data provenance and integrity gate
└── fixtures/                          # Synthetic fixtures for pre-integration verification
    ├── synthetic_scenario_trials.json
    ├── synthetic_route_trials.json
    ├── synthetic_detection_samples.json
    ├── synthetic_latency_samples.json
    ├── synthetic_cloud_sequences.json
    └── synthetic_cool_benchmarks.json
```

---

## Verification & Execution Commands

Run unit tests from this directory:

```powershell
python -m unittest -v test_metrics.py
```

Run the evaluation pipeline against synthetic fixtures:

```powershell
python run_evaluation_pipeline.py --mode synthetic
```

This prints a fixture-processing self-check without performance values or PASS
claims. It does not overwrite the submission placeholder.

For a measured report, collect real trials first and prepare a **separate**, private
`measured_data/` directory. It needs `manifest.json`, six measured summary JSON
files, and the original recordings or logs that support each summary. The
manifest must name and SHA-256 hash every summary and at least one source file
for each dataset, and record who inspected that evidence. Each summary's
`metadata` must declare `PHYSICAL_MEASURED`
and the same collection ID. See [measured_data_guide.md](measured_data_guide.md)
for the exact layout and format.

When the evidence package is complete, run:

```powershell
python run_evaluation_pipeline.py --mode measured --data-dir measured_data --out reports/measured.generated.md
```

Measured mode refuses missing inputs, copied synthetic fixtures, hash mismatches,
missing source evidence, incomplete trial counts, and missing human review.
Passing this software gate checks integrity and records the review declaration;
the reviewer must actually inspect the footage, labels, and benchmark runs.
Private recordings, participant information, and generated reports under the
listed directories are ignored by Git.
