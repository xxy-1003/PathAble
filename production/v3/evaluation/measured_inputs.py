"""Load measured evaluation inputs only when their source evidence is present.

This checks provenance records and file integrity. It cannot independently prove
that a recording depicts a physical trial; the team must review the evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path


DATASETS = {
    "detection": ("samples", list),
    "scenarios": ("trials", list),
    "routes": ("runs", list),
    "latency": ("samples_ms", list),
    "cloud": ("sequences", list),
    "cool": ("configurations", dict),
}
FIXTURE_FILES = {
    "detection": "synthetic_detection_samples.json",
    "scenarios": "synthetic_scenario_trials.json",
    "routes": "synthetic_route_trials.json",
    "latency": "synthetic_latency_samples.json",
    "cloud": "synthetic_cloud_sequences.json",
    "cool": "synthetic_cool_benchmarks.json",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _content_hash(rows: object) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a UTC timestamp")
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be a UTC timestamp")
    return timestamp


def _checked_file(directory: Path, relative: str, expected_hash: str) -> Path:
    if not isinstance(relative, str) or not relative.strip() or "synthetic" in relative.lower():
        raise ValueError("Measured input paths must be nonempty and cannot name synthetic fixtures")
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f"Measured input is missing or outside the data directory: {relative}")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError(f"Missing SHA-256 for {relative}")
    if file_sha256(path) != expected_hash.lower():
        raise ValueError(f"SHA-256 mismatch for {relative}")
    return path


def _nonnegative(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _validate_rows(data: dict) -> None:
    for row in data["detection"]:
        if (not isinstance(row, dict) or not all(
                _nonnegative(row.get(key)) for key in
                ("distance_m", "true_positives", "false_positives", "false_negatives"))):
            raise ValueError("Detection samples need measured distance and nonnegative TP/FP/FN")
    for row in data["scenarios"]:
        truth = row.get("ground_truth", {}) if isinstance(row, dict) else {}
        execution = row.get("execution", {}) if isinstance(row, dict) else {}
        if (not isinstance(truth, dict) or not isinstance(execution, dict)
                or not isinstance(row.get("scenario_id"), int)
                or not isinstance(truth.get("acceptable_actions"), list)
                or not truth["acceptable_actions"]
                or type(truth.get("safety_critical")) is not bool
                or not isinstance(execution.get("system_action"), str)):
            raise ValueError("Scenario trials need ground truth, safety label, and system action")
    for row in data["routes"]:
        if (not isinstance(row, dict) or type(row.get("reached_destination")) is not bool
                or not all(type(row.get(key)) is int and row[key] >= 0
                           for key in ("spotter_interventions", "collisions"))):
            raise ValueError("Route runs need completion, spotter, and collision records")
    if not all(_nonnegative(value) for value in data["latency"]):
        raise ValueError("Latency samples must be nonnegative measured milliseconds")
    outcomes = {"TEMPORARY", "UNCERTAIN", "LASTING"}
    for row in data["cloud"]:
        if (not isinstance(row, dict) or row.get("ground_truth_outcome") not in outcomes
                or row.get("predicted_outcome") not in outcomes
                or type(row.get("escalated_to_facilities")) is not bool):
            raise ValueError("Cloud sequences need ground truth, prediction, and escalation flag")


def load_measured_inputs(data_dir: Path, fixture_dir: Path) -> tuple[dict, dict]:
    """Return manifest and data, or refuse to label the run as measured."""
    directory = data_dir.resolve()
    if not directory.is_dir() or directory == fixture_dir.resolve():
        raise ValueError("--data-dir must be a separate existing directory of recorded evidence")
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Measured mode requires --data-dir with manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("data_origin") != "PHYSICAL_MEASURED":
        raise ValueError("Manifest must declare schema_version 1 and PHYSICAL_MEASURED")
    collection = manifest.get("collection", {})
    if not isinstance(collection, dict):
        raise ValueError("Manifest collection must be an object")
    for field in ("collection_id", "site", "recorded_by", "recorded_at_utc"):
        if not isinstance(collection.get(field), str) or not collection[field].strip():
            raise ValueError(f"Manifest collection.{field} is required")
    recorded_at = _utc_timestamp(collection["recorded_at_utc"], "collection.recorded_at_utc")
    review = manifest.get("evidence_review", {})
    if (not isinstance(review, dict) or not isinstance(review.get("reviewed_by"), str)
            or not review["reviewed_by"].strip()
            or review.get("source_files_checked") is not True
            or review.get("labels_checked") is not True
            or review.get("benchmark_runs_checked") is not True):
        raise ValueError("Manifest requires a named human evidence review of source files, labels, and benchmark runs")
    reviewed_at = _utc_timestamp(review.get("reviewed_at_utc"), "evidence_review.reviewed_at_utc")
    if reviewed_at < recorded_at:
        raise ValueError("Evidence review cannot predate the recording")

    entries = manifest.get("datasets")
    if not isinstance(entries, dict) or set(entries) != set(DATASETS):
        raise ValueError(f"Manifest must provide exactly these datasets: {', '.join(DATASETS)}")
    fixture_hashes = {file_sha256(path) for path in fixture_dir.glob("synthetic_*.json")}
    fixture_content_hashes = {}
    for name, (key, _) in DATASETS.items():
        fixture_path = fixture_dir / FIXTURE_FILES[name]
        fixture_content_hashes[name] = _content_hash(json.loads(fixture_path.read_text(encoding="utf-8"))[key])
    loaded = {}
    evidence_paths = set()
    for name, (key, expected_type) in DATASETS.items():
        entry = entries[name]
        if not isinstance(entry, dict):
            raise ValueError(f"datasets.{name} must be an object")
        path = _checked_file(directory, entry.get("file"), entry.get("sha256"))
        if file_sha256(path) in fixture_hashes:
            raise ValueError(f"datasets.{name} is a copied synthetic fixture")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"datasets.{name} requires at least one hashed source recording or log")
        for source in evidence:
            if not isinstance(source, dict):
                raise ValueError(f"datasets.{name} evidence entries must be objects")
            source_path = _checked_file(directory, source.get("file"), source.get("sha256"))
            if source_path == path:
                raise ValueError(f"datasets.{name} evidence cannot be its own summary file")
            if source_path.stat().st_size == 0 or source_path in evidence_paths:
                raise ValueError(f"datasets.{name} requires a nonempty, distinct source recording or log")
            evidence_paths.add(source_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"datasets.{name} summary must be a JSON object")
        metadata = payload.get("metadata", {})
        if (not isinstance(metadata, dict) or metadata.get("data_origin") != "PHYSICAL_MEASURED"
                or metadata.get("collection_id") != collection["collection_id"]
                or "fixture_type" in metadata):
            raise ValueError(f"datasets.{name} lacks matching measured provenance metadata")
        rows = payload.get(key)
        if not isinstance(rows, expected_type) or not rows:
            raise ValueError(f"datasets.{name} requires a nonempty {key} field")
        if _content_hash(rows) == fixture_content_hashes[name]:
            raise ValueError(f"datasets.{name} contains bundled synthetic fixture values")
        loaded[name] = rows

    if len(loaded["scenarios"]) < 80 or len(loaded["routes"]) < 20 or len(loaded["cloud"]) < 30:
        raise ValueError("Measured submission needs at least 80 scenarios, 20 route runs, and 30 cloud sequences")
    _validate_rows(loaded)
    cool = loaded["cool"]
    if not {"config_a", "config_b"}.issubset(cool):
        raise ValueError("Measured COOL data needs both COOL and stock Graviton configurations")
    for key, config in cool.items():
        if not isinstance(config, dict):
            raise ValueError(f"Measured COOL {key} must be a configuration object")
        frame_count = config.get("total_frames")
        timings = config.get("latencies_ms")
        if (type(frame_count) is not int or frame_count < 300
                or not isinstance(timings, list) or len(timings) < frame_count
                or not all(_nonnegative(value) for value in timings)
                or not _nonnegative(config.get("total_time_s"))
                or config["total_time_s"] <= 0
                or not _nonnegative(config.get("hourly_rate"))
                or config["hourly_rate"] <= 0
                or not isinstance(config.get("instance_type"), str)
                or not config.get("input_manifest_sha256")
                or not config.get("model_sha256")):
            raise ValueError(f"Measured COOL {key} lacks recorded frame timings, hardware, or verified cost input")
    if cool["config_a"].get("provider") != "cool" or cool["config_b"].get("provider") != "stock":
        raise ValueError("Measured COOL config_a must use COOL and config_b must use stock OpenCV")
    if (cool["config_a"]["instance_type"] != cool["config_b"]["instance_type"]
            or cool["config_a"]["input_manifest_sha256"] != cool["config_b"]["input_manifest_sha256"]
            or cool["config_a"]["model_sha256"] != cool["config_b"]["model_sha256"]):
        raise ValueError("COOL and stock Graviton runs must share hardware, input manifest, and model")
    return manifest, loaded
