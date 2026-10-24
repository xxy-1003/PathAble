"""PathAble Evaluation Pipeline Runner (Person 5, evidence gated).

Loads scenario trials, route tests, latency records, cloud sequences, and COOL benchmark data.
Computes and formats the official evaluation metrics report for the technical paper and submission.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from measured_inputs import DATASETS, FIXTURE_FILES, load_measured_inputs
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


def load_inputs(mode: str, data_dir: Path | None) -> tuple[dict, dict]:
    if mode == "measured":
        if data_dir is None:
            raise ValueError("--mode measured requires --data-dir with recorded evidence and manifest.json")
        return load_measured_inputs(data_dir, FIXTURES_DIR)
    if mode != "synthetic" or data_dir is not None:
        raise ValueError("Synthetic mode uses bundled fixtures and does not accept --data-dir")
    loaded = {}
    for name, filename in FIXTURE_FILES.items():
        payload = json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
        loaded[name] = payload[DATASETS[name][0]]
    return {}, loaded


def run_pipeline(mode: str = "synthetic", output_file: Path | None = None,
                 data_dir: Path | None = None) -> str:
    manifest, data = load_inputs(mode, data_dir)
    origin = "PHYSICAL_MEASURED" if mode == "measured" else "SYNTHETIC_FIXTURE"
    report_date = datetime.now(timezone.utc).date().isoformat()
    if mode == "synthetic":
        lines = [
            "# PathAble v3: Synthetic Evaluation Self-Check", "",
            "**Data Status**: `SYNTHETIC_FIXTURE`", f"**Report Date (UTC)**: {report_date}", "",
            "> Pipeline self-check only. These are generated fixtures. Performance values",
            "> and pass/fail claims are deliberately omitted from this report. Do not use it",
            "> as competition or demo evidence.", "",
            "| Fixture | Records processed |", "| :--- | ---: |",
        ]
        lines.extend(f"| {name} | {len(records)} |" for name, records in data.items())
        report = "\n".join(lines) + "\n"
        if output_file is not None:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(report, encoding="utf-8")
        return report

    det_res = calculate_detection_metrics(data["detection"], data_origin=origin)
    scen_res = calculate_decision_accuracy(data["scenarios"], data_origin=origin)
    route_res = calculate_route_completion(data["routes"], data_origin=origin)
    lat_res = calculate_latency_percentiles(data["latency"], data_origin=origin)
    esc_res = calculate_escalation_accuracy(data["scenarios"], data_origin=origin)
    cloud_res = calculate_cloud_metrics(data["cloud"], data_origin=origin)
    cool_res = calculate_cool_performance(data["cool"], data_origin=origin)

    collection = manifest["collection"]
    review = manifest["evidence_review"]
    report_lines = [
        "# PathAble v3: Evaluation Results & Metrics Summary",
        "",
        f"**Data Status**: `{origin}`",
        f"**Report Date (UTC)**: {report_date}",
        f"**Collection ID**: `{collection['collection_id']}`",
        f"**Site**: {collection['site']}",
        f"**Recorded at (UTC)**: {collection['recorded_at_utc']}",
        f"**Recorder**: {collection['recorded_by']}",
        f"**Evidence reviewed by**: {review['reviewed_by']} at {review['reviewed_at_utc']}",
        "",
        "> Input and source-file hashes match the measured manifest. The named reviewer",
        "> attests that source files, labels, and benchmark runs were inspected. Confirm",
        "> consent and trial protocol before publishing participant results.",
        "",
    ]

    report_lines.extend([
        "## Summary Scorecard against Proposal Targets",
        "",
        "| Metric | Proposal Target | Measured Value | Status |",
        "| :--- | :---: | :---: | :---: |",
        f"| Obstacle Detection Recall ({det_res['sample_count']} samples) | $\\ge 0.90$ | {det_res['recall']:.2f} | {'PASS' if det_res['recall'] >= .90 else 'FAIL'} |",
        f"| Obstacle Detection Precision | $\\ge 0.85$ | {det_res['precision']:.2f} | {'PASS' if det_res['precision'] >= .85 else 'FAIL'} |",
        f"| Decision Accuracy ({scen_res['total_trials']} trials) | $\\ge 85\\%$ | {scen_res['accuracy_pct']}% | {'PASS' if scen_res['target_met'] else 'FAIL'} |",
        f"| Route Completion ({route_res['total_runs']} runs) | $\\ge 90\\%$ | {route_res['completion_rate_pct']}% | {'PASS' if route_res['target_met'] else 'FAIL'} |",
        f"| Collisions | 0 | {route_res['collisions']} | {'PASS' if route_res['collisions'] == 0 else 'FAIL'} |",
        f"| End-to-end Latency p95 ({lat_res['sample_count']} samples) | $\\le 700\\text{{ ms}}$ | {lat_res['p95_ms']} ms | {'PASS' if lat_res['target_met'] else 'FAIL'} |",
        f"| Escalation Recall | $\\ge 0.90$ | {esc_res['recall']:.2f} | {'PASS' if esc_res['target_met'] else 'FAIL'} |",
        f"| Cloud Classification ({cloud_res['total_sequences']} sequences) | $\\ge 80\\%$ | {cloud_res['accuracy_pct']}% | {'PASS' if cloud_res['accuracy_pct'] >= 80 else 'FAIL'} |",
        f"| False Escalations to Facilities | $\\le 1 \\text{{ in }} 30$ | {cloud_res['false_escalations_to_facilities']} | {'PASS' if cloud_res['false_escalations_to_facilities'] <= 1 else 'FAIL'} |",
        "",
        "## COOL Comparison (Review Raw Benchmark Runs Before Citing)",
        "",
        "| Configuration | Median Latency (ms) | p95 Latency (ms) | Throughput (FPS) | Cost / 1k Frames (USD) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for cfg in cool_res["configurations"].values():
        report_lines.append(
            f"| {cfg['name']} | {cfg['median_latency_ms']} | {cfg['p95_latency_ms']} | {cfg['throughput_fps']} | ${cfg['cost_per_1000_frames_usd']:.6f} |"
        )
    speedup = cool_res.get("speedup_a_vs_b_graviton")
    report_lines.extend(["", f"COOL / stock Graviton throughput ratio: **{speedup}x**." if speedup
                         else "COOL / stock Graviton throughput ratio: unavailable."])

    report_content = "\n".join(report_lines) + "\n"

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(report_content, encoding="utf-8")
    return report_content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PathAble Evaluation Pipeline")
    parser.add_argument("--mode", choices=["synthetic", "measured"], default="synthetic")
    parser.add_argument("--data-dir", type=Path, help="recorded data, manifest, and source evidence directory")
    parser.add_argument("--out", type=Path, help="optional report path; stdout only by default")
    args = parser.parse_args()
    try:
        print(run_pipeline(mode=args.mode, output_file=args.out, data_dir=args.data_dir), end="")
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
