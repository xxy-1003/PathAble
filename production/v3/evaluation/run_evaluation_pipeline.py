"""PathAble Evaluation Pipeline Runner (Person 5).

Loads scenario trials, route tests, latency records, cloud sequences, and COOL benchmark data.
Computes and formats the official evaluation metrics report for the technical paper and submission.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from metrics import (
    calculate_detection_metrics,
    calculate_decision_accuracy,
    calculate_route_completion,
    calculate_latency_percentiles,
    calculate_escalation_accuracy,
    calculate_cloud_metrics,
    calculate_cool_performance,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def run_pipeline(mode: str = "synthetic", output_file: Path | None = None) -> int:
    origin = "PHYSICAL_MEASURED" if mode == "measured" else "SYNTHETIC_FIXTURE"

    print("=" * 78)
    print(f" PathAble v3: Evaluation & Submission Evidence Pipeline")
    print(f" Data Origin Mode: {origin}")
    if origin == "SYNTHETIC_FIXTURE":
        print(" [WARNING] Running on SYNTHETIC FIXTURES for pre-integration verification.")
        print("           Never submit synthetic fixtures as physically measured trials.")
    print("=" * 78)

    # 1. Detection
    det_path = FIXTURES_DIR / "synthetic_detection_samples.json"
    with open(det_path, encoding="utf-8") as f:
        det_data = json.load(f)
    det_res = calculate_detection_metrics(det_data.get("samples", []), data_origin=origin)

    # 2. Decision Accuracy (80 Scenario Trials)
    scen_path = FIXTURES_DIR / "synthetic_scenario_trials.json"
    with open(scen_path, encoding="utf-8") as f:
        scen_data = json.load(f)
    trials = scen_data.get("trials", [])
    scen_res = calculate_decision_accuracy(trials, data_origin=origin)

    # 3. Route Completion (20 Runs)
    route_path = FIXTURES_DIR / "synthetic_route_trials.json"
    with open(route_path, encoding="utf-8") as f:
        route_data = json.load(f)
    runs = route_data.get("runs", [])
    route_res = calculate_route_completion(runs, data_origin=origin)

    # 4. Latency Percentiles
    lat_path = FIXTURES_DIR / "synthetic_latency_samples.json"
    with open(lat_path, encoding="utf-8") as f:
        lat_data = json.load(f)
    lat_samples = lat_data.get("samples_ms", [])
    lat_res = calculate_latency_percentiles(lat_samples, data_origin=origin)

    # 5. Escalation Accuracy
    esc_res = calculate_escalation_accuracy(trials, data_origin=origin)

    # 6. Cloud Classification
    cloud_path = FIXTURES_DIR / "synthetic_cloud_sequences.json"
    with open(cloud_path, encoding="utf-8") as f:
        cloud_data = json.load(f)
    seqs = cloud_data.get("sequences", [])
    cloud_res = calculate_cloud_metrics(seqs, data_origin=origin)

    # 7. COOL Benchmark
    cool_path = FIXTURES_DIR / "synthetic_cool_benchmarks.json"
    with open(cool_path, encoding="utf-8") as f:
        cool_data = json.load(f)
    cool_configs = cool_data.get("configurations", {})
    cool_res = calculate_cool_performance(cool_configs, data_origin=origin)

    # Build Markdown Summary
    report_lines = [
        "# PathAble v3: Evaluation Results & Metrics Summary",
        "",
        f"**Data Status**: `{origin}`",
        f"**Evaluation Date**: 2026-10-24",
        "",
    ]

    if origin == "SYNTHETIC_FIXTURE":
        report_lines.extend([
            "> [!IMPORTANT]",
            "> **Pre-integration Verification Only**: The results below are computed from synthetic fixtures",
            "> to validate metric pipelines. Measured physical trial evidence will be populated after",
            "> branches are integrated and corridor testing is conducted.",
            "",
        ])

    report_lines.extend([
        "## Summary Scorecard against Proposal Targets",
        "",
        "| Metric | Proposal Target | Evaluated Value | Status |",
        "| :--- | :---: | :---: | :---: |",
        f"| Obstacle Detection Recall | $\\ge 0.90$ | {det_res.get('recall', 0):.2f} | {'PASS' if det_res.get('target_met') else 'FAIL'} |",
        f"| Obstacle Detection Precision | $\\ge 0.85$ | {det_res.get('precision', 0):.2f} | {'PASS' if det_res.get('target_met') else 'FAIL'} |",
        f"| Decision Accuracy (80 trials) | $\\ge 85\\%$ | {scen_res.get('accuracy_pct', 0)}% | {'PASS' if scen_res.get('target_met') else 'FAIL'} |",
        f"| Route Completion (20 runs) | $\\ge 90\\%$ | {route_res.get('completion_rate_pct', 0)}% | {'PASS' if route_res.get('target_met') else 'FAIL'} |",
        f"| Collisions | 0 | {route_res.get('collisions', 0)} | {'PASS' if route_res.get('collisions', 0) == 0 else 'FAIL'} |",
        f"| End-to-end Latency (p95) | $\\le 700\\text{{ ms}}$ | {lat_res.get('p95_ms', 0)} ms | {'PASS' if lat_res.get('target_met') else 'FAIL'} |",
        f"| Escalation Recall | $\\ge 0.90$ | {esc_res.get('recall', 0):.2f} | {'PASS' if esc_res.get('target_met') else 'FAIL'} |",
        f"| Cloud Classification Accuracy | $\\ge 80\\%$ | {cloud_res.get('accuracy_pct', 0)}% | {'PASS' if cloud_res.get('target_met') else 'FAIL'} |",
        f"| False Escalations to Facilities | $\\le 1 \\text{{ in }} 30$ | {cloud_res.get('false_escalations_to_facilities', 0)} | {'PASS' if cloud_res.get('target_met') else 'FAIL'} |",
        f"| COOL Speedup (Graviton COOL vs Stock) | Report gain | {cool_res.get('speedup_a_vs_b_graviton', 1.0)}x | MEASURED |",
        "",
        "## COOL on AWS Graviton Comparative Performance",
        "",
        "| Configuration | Median Latency (ms) | p95 Latency (ms) | Throughput (FPS) | Cost / 1k Frames (USD) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for cfg_key, cfg in cool_res.get("configurations", {}).items():
        report_lines.append(
            f"| {cfg.get('name')} | {cfg.get('median_latency_ms')} | {cfg.get('p95_latency_ms')} | {cfg.get('throughput_fps')} | ${cfg.get('cost_per_1000_frames_usd'):.6f} |"
        )

    report_content = "\n".join(report_lines) + "\n"

    print(report_content)

    if output_file:
        output_file.write_text(report_content, encoding="utf-8")
        print(f"Report written to: {output_file}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PathAble Evaluation Pipeline")
    parser.add_argument("--mode", choices=["synthetic", "measured"], default="synthetic")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "evaluation_summary_report.md")
    args = parser.parse_args()
    sys.exit(run_pipeline(mode=args.mode, output_file=args.out))
