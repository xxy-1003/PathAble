"""Compare complete benchmark records only when their fixed input hashes match."""

import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cool-graviton", type=Path, required=True)
    p.add_argument("--stock-graviton", type=Path, required=True)
    p.add_argument("--stock-x86", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    pairs = [("COOL Graviton", load(args.cool_graviton)),
             ("Stock OpenCV Graviton", load(args.stock_graviton))]
    if args.stock_x86:
        pairs.append(("Stock OpenCV x86", load(args.stock_x86)))
    reasons = []
    manifests = {record.get("dataset_manifest_sha256") for _, record in pairs}
    inputs = {tuple(row.get("sha256") for row in record.get("input_files", [])) for _, record in pairs}
    labels = {record.get("dataset_label") for _, record in pairs}
    if len(manifests) != 1 or len(inputs) != 1:
        reasons.append("configurations do not have the same manifest and file hashes")
    if len(labels) != 1:
        reasons.append("configurations have different dataset labels")
    if labels != {"recorded"}:
        reasons.append("synthetic inputs cannot support a performance comparison")
    if any(record.get("fixed_input_count") != 300 for _, record in pairs):
        reasons.append("every recorded configuration must process the proposal's 300 keyframes")
    model_hashes = {record.get("model", {}).get("sha256") for _, record in pairs}
    if len(model_hashes) != 1 or None in model_hashes:
        reasons.append("configurations do not report the same model hash")
    if any(record.get("status") != "complete" for _, record in pairs):
        reasons.append("one or more runs are incomplete")
    if any(not record.get("environment", {}).get("provider_evidence", {}).get("verified")
           for _, record in pairs):
        reasons.append("provider evidence is missing or unverified")
    cool, stock = pairs[0][1], pairs[1][1]
    cool_env, stock_env = cool.get("environment", {}), stock.get("environment", {})
    if cool.get("provider") != "cool" or stock.get("provider") != "stock":
        reasons.append("the first two inputs must be a COOL run followed by a stock OpenCV run")
    if not cool_env.get("instance_type") or not stock_env.get("instance_type"):
        reasons.append("Graviton instance type is not recorded")
    if cool_env.get("instance_type") != stock_env.get("instance_type"):
        reasons.append("Graviton configurations do not report the same instance type")
    if "aarch64" not in str(cool_env.get("architecture", "")).lower() and "arm" not in str(
            cool_env.get("architecture", "")).lower():
        reasons.append("COOL run architecture is not identified as Arm")
    if "aarch64" not in str(stock_env.get("architecture", "")).lower() and "arm" not in str(
            stock_env.get("architecture", "")).lower():
        reasons.append("stock Graviton run architecture is not identified as Arm")
    if len(pairs) > 2:
        x86_env = pairs[2][1].get("environment", {})
        if "x86" not in str(x86_env.get("architecture", "")).lower() and "amd64" not in str(
                x86_env.get("architecture", "")).lower():
            reasons.append("planned x86 run architecture is not identified as x86_64")
    results = []
    for label, record in pairs:
        results.append({"configuration": label,
                        "status": record.get("status"),
                        "dataset_label": record.get("dataset_label"),
                        "instance_type": record.get("environment", {}).get("instance_type"),
                        "architecture": record.get("environment", {}).get("architecture"),
                        "ami_id": record.get("environment", {}).get("ami_id"),
                        "opencv_version": record.get("environment", {}).get("opencv_version"),
                        "build_label": record.get("build_label"),
                        "summary": record.get("summary"),
                        "input_count": record.get("fixed_input_count")})
    report = {"comparison_status": "comparable" if not reasons else "incomplete_or_unmatched",
              "comparison_blockers": reasons,
              "ready_for_manual_review": not reasons,
              "rule": "No speedup is computed by this script. Compare summaries only when status is comparable.",
              "configurations": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if reasons:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
