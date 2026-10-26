"""Read Person 4's native run.json files without inventing missing results."""

import json
import math
from pathlib import Path
import statistics

from metrics import calculate_latency_percentiles


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value.lower()))


def load_recorded_benchmarks(directory: Path, configurations: dict, checked_file,
                             evidence_paths: set[Path]) -> dict:
    """Validate the recorded comparison and derive metrics from its raw runs.

    Hashes and provider declarations still require the manifest's human review.
    Missing pricing produces an unavailable cost, rather than an assumed price.
    """
    if not {"config_a", "config_b"}.issubset(configurations) or not set(configurations) <= {
            "config_a", "config_b", "config_c"}:
        raise ValueError("Measured benchmark needs config_a (COOL) and config_b (stock Graviton)")
    records = {}
    results = {}
    throughputs = {}
    labels = {"config_a": "COOL Graviton", "config_b": "Stock OpenCV Graviton",
              "config_c": "Stock OpenCV x86"}
    for key, reference in configurations.items():
        if not isinstance(reference, dict):
            raise ValueError(f"Benchmark {key} must reference a hashed native run.json")
        path = checked_file(directory, reference.get("file"), reference.get("sha256"))
        if path not in evidence_paths:
            raise ValueError(f"Benchmark {key} run.json must also be listed as source evidence")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("schema_version") != 1
                or record.get("status") != "complete" or record.get("dataset_label") != "recorded"
                or record.get("fixed_input_count") != 300):
            raise ValueError(f"Benchmark {key} requires a complete recorded 300-keyframe run.json")
        provider = "cool" if key == "config_a" else "stock"
        env = record.get("environment", {})
        if (record.get("provider") != provider or not isinstance(env, dict)
                or not isinstance(env.get("provider_evidence"), dict)
                or env.get("provider_evidence", {}).get("verified") is not True
                or not env.get("instance_type") or not env.get("ami_id")):
            raise ValueError(f"Benchmark {key} lacks verified provider or AWS hardware evidence")
        architecture = str(env.get("architecture", "")).lower()
        expected_arch = ("x86", "amd64") if key == "config_c" else ("arm", "aarch64")
        if not any(value in architecture for value in expected_arch):
            raise ValueError(f"Benchmark {key} has the wrong architecture")
        inputs = record.get("input_files", [])
        model = record.get("model", {})
        if (not isinstance(inputs, list) or len(inputs) != 300
                or not all(isinstance(row, dict) and _sha(row.get("sha256")) for row in inputs)
                or not _sha(record.get("dataset_manifest_sha256"))
                or not isinstance(model, dict) or not _sha(model.get("sha256"))):
            raise ValueError(f"Benchmark {key} lacks original input and model hashes")
        protocol = record.get("protocol", {})
        runs = record.get("runs", [])
        if (not isinstance(protocol, dict) or not isinstance(runs, list)
                or not all(isinstance(run, dict) and run.get("phase") in {"warmup", "measured"}
                           for run in runs)
                or protocol.get("same_input_order_each_run") is not True):
            raise ValueError(f"Benchmark {key} lacks repeatable run protocol")
        for phase, minimum in (("warmup", 3), ("measured", 5)):
            phase_runs = [run for run in runs if isinstance(run, dict) and run.get("phase") == phase]
            if len(phase_runs) < minimum or protocol.get(f"{phase}_runs") != len(phase_runs):
                raise ValueError(f"Benchmark {key} needs at least {minimum} complete {phase} runs")
            for run in phase_runs:
                timings = run.get("latency_ms", [])
                if (run.get("completed") is not True or run.get("frame_count") != 300
                        or not isinstance(timings, list) or len(timings) != 300
                        or not all(_number(value) for value in timings)
                        or not _number(run.get("wall_s")) or run["wall_s"] == 0
                        or not isinstance(run.get("outputs"), list) or len(run["outputs"]) != 300):
                    raise ValueError(f"Benchmark {key} has incomplete raw {phase} timings or outputs")
        measured = [run for run in runs if run.get("phase") == "measured"]
        latency = calculate_latency_percentiles([value for run in measured for value in run["latency_ms"]])
        throughput = statistics.median(300 / run["wall_s"] for run in measured)
        pricing = record.get("cost_assumptions", {})
        if not isinstance(pricing, dict) or pricing.get("currency") != "USD":
            raise ValueError(f"Benchmark {key} must declare USD cost assumptions")
        ec2, marketplace = pricing.get("ec2_hourly_usd"), pricing.get("marketplace_hourly_usd")
        for rate in (ec2, marketplace):
            if rate is not None and not _number(rate):
                raise ValueError(f"Benchmark {key} has an invalid hourly rate")
        cost = ((ec2 + marketplace) / (throughput * 3600) * 1000
                if ec2 is not None and marketplace is not None else None)
        results[key] = {"name": f"{labels[key]} ({env['instance_type']})",
                        "median_latency_ms": latency["median_ms"],
                        "p95_latency_ms": latency["p95_ms"], "throughput_fps": round(throughput, 2),
                        "cost_per_1000_frames_usd": cost, "measured_runs": len(measured)}
        records[key] = record
        throughputs[key] = throughput
    reference = records["config_a"]
    for key, record in records.items():
        if (record["dataset_manifest_sha256"] != reference["dataset_manifest_sha256"]
                or record["input_files"] != reference["input_files"]
                or record["model"]["sha256"] != reference["model"]["sha256"]
                or record.get("calibration_files") != reference.get("calibration_files")):
            raise ValueError(f"Benchmark {key} does not use identical inputs, model, and calibration")
    if records["config_b"]["environment"]["instance_type"] != reference["environment"]["instance_type"]:
        raise ValueError("COOL and stock Graviton runs must use the same instance type")
    return {"configurations": results,
            "speedup_a_vs_b_graviton": round(throughputs["config_a"] / throughputs["config_b"], 2)}
