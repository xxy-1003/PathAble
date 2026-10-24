"""Run a fixed keyframe manifest under one OpenCV configuration."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

V3_ROOT = Path(__file__).resolve().parents[1]
if str(V3_ROOT) not in sys.path:
    sys.path.insert(0, str(V3_ROOT))

cv2 = None
RecordedRechecker = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    expected = {"sequence_id", "timestamp_s", "path"}
    if not rows or set(rows[0]) != expected:
        raise ValueError("manifest.csv needs columns sequence_id,timestamp_s,path and at least one row")
    items = []
    for row in rows:
        image = (path.parent / row["path"]).resolve()
        if not image.is_file():
            raise ValueError(f"Missing keyframe: {image}")
        items.append({"sequence_id": row["sequence_id"],
                      "timestamp_s": float(row["timestamp_s"]), "path": image,
                      "sha256": sha256(image)})
    closed_sequences = set()
    previous_sequence = None
    last_timestamp = {}
    for item in items:
        sequence = item["sequence_id"]
        if sequence != previous_sequence:
            if sequence in closed_sequences:
                raise ValueError("each sequence_id must occupy one contiguous manifest block")
            if previous_sequence is not None:
                closed_sequences.add(previous_sequence)
        if sequence in last_timestamp and item["timestamp_s"] <= last_timestamp[sequence]:
            raise ValueError("timestamps must strictly increase within each sequence")
        last_timestamp[sequence] = item["timestamp_s"]
        previous_sequence = sequence
    return items


def imds(path: str) -> str | None:
    token_request = urllib.request.Request(
        "http://169.254.169.254/latest/api/token", method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    try:
        with urllib.request.urlopen(token_request, timeout=0.4) as response:
            token = response.read().decode()
        request = urllib.request.Request(
            f"http://169.254.169.254/latest/meta-data/{path}",
            headers={"X-aws-ec2-metadata-token": token})
        with urllib.request.urlopen(request, timeout=0.4) as response:
            return response.read().decode().strip()
    except (OSError, urllib.error.URLError, TimeoutError):
        return None


def environment(provider: str) -> dict:
    cv_path = str(Path(cv2.__file__).resolve())
    build = cv2.getBuildInformation()
    cool_root = Path(os.environ.get("COOL_ROOT", "/opt/cool")).resolve()
    path_in_cool = Path(cv_path).is_relative_to(cool_root)
    build_markers = [line.strip() for line in build.splitlines()
                     if any(term in line.lower() for term in ("kleidi", "cool", "opencl"))]
    if provider == "cool":
        evidence = path_in_cool
        evidence_text = "cv2 module resolved beneath COOL_ROOT; full OpenCV build information captured"
    else:
        evidence = not path_in_cool and not any("kleidi" in line.lower() or "cool" in line.lower()
                                                for line in build_markers)
        evidence_text = "cv2 module outside COOL_ROOT and no COOL/Kleidi build marker"
    return {
        "python": sys.version,
        "opencv_version": cv2.__version__,
        "opencv_module_path": cv_path,
        "opencv_build_information": build,
        "opencv_build_markers": build_markers,
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "hostname": platform.node(),
        "instance_type": os.environ.get("BENCH_INSTANCE_TYPE") or imds("instance-type"),
        "ami_id": os.environ.get("BENCH_AMI_ID") or imds("ami-id"),
        "cool_root": str(cool_root),
        "provider_evidence": {"expected": provider, "verified": evidence,
                              "method": evidence_text},
    }


def main():
    global cv2, RecordedRechecker
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--provider", choices=("cool", "stock"), required=True)
    parser.add_argument("--dataset-label", choices=("recorded", "synthetic"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--camera-calibration", type=Path)
    parser.add_argument("--floor-calibration", type=Path)
    parser.add_argument("--same-pose-verified", action="store_true")
    parser.add_argument("--corridor-x-limits-m", type=float, nargs=2,
                        metavar=("LEFT", "RIGHT"),
                        help="measured corridor wall limits in the floor calibration x axis")
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--ec2-hourly-usd", type=float)
    parser.add_argument("--marketplace-hourly-usd", type=float)
    parser.add_argument("--build-label", default="unspecified")
    parser.add_argument("--cool-version", default=os.environ.get("COOL_VERSION"))
    args = parser.parse_args()
    if args.warmups < 0 or args.runs < 1:
        parser.error("warmups must be >= 0 and runs must be >= 1")
    if any(value is not None and value < 0 for value in
           (args.ec2_hourly_usd, args.marketplace_hourly_usd)):
        parser.error("hourly price assumptions cannot be negative")
    if args.provider == "cool" and not args.cool_version:
        parser.error("--cool-version (or COOL_VERSION) is required for a COOL run")

    try:
        import cv2 as cv2_module
        cv2 = cv2_module
        from recheck import RecordedRechecker as rechecker_class
        RecordedRechecker = rechecker_class
    except ModuleNotFoundError as exc:
        parser.error(f"missing runtime dependency {exc.name}; install the v3 vision requirements")

    items = read_manifest(args.manifest)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = environment(args.provider)
    record = {
        "schema_version": 1,
        "status": "incomplete",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_label": args.dataset_label,
        "dataset_manifest": str(args.manifest.resolve()),
        "dataset_manifest_sha256": sha256(args.manifest),
        "fixed_input_count": len(items),
        "input_files": [{"sequence_id": r["sequence_id"], "timestamp_s": r["timestamp_s"],
                         "path": r["path"].name, "sha256": r["sha256"]} for r in items],
        "provider": args.provider,
        "cool_version": args.cool_version if args.provider == "cool" else None,
        "build_label": args.build_label,
        "model": {"path": args.model.name, "sha256": sha256(args.model) if args.model.is_file() else None},
        "calibration_files": {
            "camera_sha256": sha256(args.camera_calibration)
            if args.camera_calibration and args.camera_calibration.is_file() else None,
            "floor_sha256": sha256(args.floor_calibration)
            if args.floor_calibration and args.floor_calibration.is_file() else None,
            "same_pose_verified": args.same_pose_verified,
            "corridor_x_limits_m": args.corridor_x_limits_m,
        },
        "environment": env,
        "protocol": {"warmup_runs": args.warmups, "measured_runs": args.runs,
                     "same_input_order_each_run": True,
                     "latency_scope": "per-keyframe re-check including image decode"},
        "cost_assumptions": {"ec2_hourly_usd": args.ec2_hourly_usd,
                              "marketplace_hourly_usd": args.marketplace_hourly_usd,
                              "currency": "USD", "excludes": ["EBS", "data transfer", "tax", "other services"]},
        "runs": [],
    }
    try:
        if args.dataset_label == "recorded" and len(items) != 300:
            raise ValueError(f"recorded proposal dataset requires exactly 300 keyframes; found {len(items)}")
        if not env["provider_evidence"]["verified"]:
            raise RuntimeError("OpenCV provider could not be verified; refusing to label this run as " + args.provider)
        if not args.model.is_file():
            raise FileNotFoundError(f"ONNX model not found: {args.model}")
        detector = RecordedRechecker(args.model, args.camera_calibration, args.floor_calibration,
                                     same_pose_verified=args.same_pose_verified,
                                     corridor_x_limits_m=tuple(args.corridor_x_limits_m)
                                     if args.corridor_x_limits_m else None)
        for phase, count in (("warmup", args.warmups), ("measured", args.runs)):
            for index in range(count):
                latencies = []
                run_started = time.perf_counter()
                outputs = []
                for item in items:
                    start = time.perf_counter()
                    outputs.append(detector.recheck(item["sequence_id"], item["path"], item["timestamp_s"]))
                    latencies.append((time.perf_counter() - start) * 1000)
                wall_s = time.perf_counter() - run_started
                run = {"phase": phase, "index": index + 1, "completed": True,
                       "frame_count": len(items), "wall_s": wall_s,
                       "throughput_fps": len(items) / wall_s if wall_s else None,
                       "latency_ms": latencies, "outputs": outputs}
                record["runs"].append(run)
                # Reset temporal state between repeats so each run begins with
                # identical first-keyframe semantics.
                detector.previous.clear()
        measured = [x for x in record["runs"] if x["phase"] == "measured"]
        all_latencies = [v for run in measured for v in run["latency_ms"]]
        hourly = (args.ec2_hourly_usd or 0.0) + (args.marketplace_hourly_usd or 0.0)
        throughput = statistics.median(x["throughput_fps"] for x in measured)
        record["summary"] = {
            "frame_latency_median_ms": statistics.median(all_latencies),
            "frame_latency_p95_ms": float(np_percentile(all_latencies, 95)),
            "median_run_throughput_fps": throughput,
            "cost_per_1000_frames_usd": (hourly / (throughput * 3600) * 1000
                                         if throughput and args.ec2_hourly_usd is not None
                                         and args.marketplace_hourly_usd is not None else None),
            "cost_note": "Requires both EC2 and Marketplace hourly rates; null if either is missing.",
        }
        record["status"] = "complete"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    target = output / "run.json"
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "output": str(target),
                      "error": record.get("error"), "summary": record.get("summary")}, indent=2))
    if record["status"] != "complete":
        raise SystemExit(2)


def np_percentile(values, percentile):
    # Linear interpolation, matching the common NumPy percentile definition.
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * percentile / 100
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


if __name__ == "__main__":
    main()
