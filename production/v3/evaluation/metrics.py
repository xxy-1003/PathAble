"""PathAble Evaluation Metric Calculations (Proposal Section 12).

Provides metric evaluation for:
1. Obstacle Detection (Recall, Precision within 2.5 m)
2. Decision Accuracy (80 scenario trials, target >= 85%)
3. Route Completion Rate (20 end-to-end runs, target >= 90%, zero collisions)
4. Whole-pipeline & Speech Latency (median, p95 <= 700 ms)
5. Escalation Accuracy (Recall of STOP_AND_ESCALATE >= 0.90)
6. Cloud Classification (temporary/uncertain/lasting >= 80%, false escalations <= 1 in 30)
7. COOL on Graviton Performance (latency, throughput fps, cost per 1000 frames)

IMPORTANT:
Every calculation report explicitly identifies whether its data origin is:
- 'SYNTHETIC_FIXTURE' (pre-integration synthetic test harness)
- 'PHYSICAL_MEASURED' (actual corridor/cloud recorded trials)
Never claim a synthetic result as a measured physical result.
"""

from __future__ import annotations

import math
from typing import Any, Literal

DataOrigin = Literal["SYNTHETIC_FIXTURE", "PHYSICAL_MEASURED"]


def calculate_detection_metrics(
    eval_samples: list[dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
    max_distance_m: float = 2.5,
) -> dict[str, Any]:
    """Calculates precision, recall, and F1 for obstacle detections within range.

    Each item in eval_samples represents a frame evaluation with:
        'true_positives': int,
        'false_positives': int,
        'false_negatives': int,
        'distance_m': float (optional, filtered if > max_distance_m)
    """
    tp = sum(
        s.get("true_positives", 0)
        for s in eval_samples
        if s.get("distance_m", 0.0) <= max_distance_m
    )
    fp = sum(
        s.get("false_positives", 0)
        for s in eval_samples
        if s.get("distance_m", 0.0) <= max_distance_m
    )
    fn = sum(
        s.get("false_negatives", 0)
        for s in eval_samples
        if s.get("distance_m", 0.0) <= max_distance_m
    )

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "data_origin": data_origin,
        "sample_count": len(eval_samples),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "target_met": recall >= 0.90 and precision >= 0.85,
    }


def calculate_decision_accuracy(
    trials: list[dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Evaluates agent decision accuracy across the 80 scenario trials.

    Each trial dict must supply:
        'scenario_id': int (1-8),
        'execution': {'system_action': str},
        'ground_truth': {'acceptable_actions': list[str]}
    """
    total = len(trials)
    if total == 0:
        return {"data_origin": data_origin, "error": "No trials provided"}

    correct = 0
    by_scenario: dict[int, dict[str, int]] = {}

    for t in trials:
        scen_id = t.get("scenario_id", 0)
        if scen_id not in by_scenario:
            by_scenario[scen_id] = {"total": 0, "correct": 0}
        by_scenario[scen_id]["total"] += 1

        chosen_action = t.get("execution", {}).get("system_action", "")
        acceptable = t.get("ground_truth", {}).get("acceptable_actions", [])

        if chosen_action in acceptable:
            correct += 1
            by_scenario[scen_id]["correct"] += 1

    accuracy = correct / total
    return {
        "data_origin": data_origin,
        "total_trials": total,
        "correct_decisions": correct,
        "accuracy_pct": round(accuracy * 100.0, 2),
        "target_met": accuracy >= 0.85,
        "scenario_breakdown": {
            s: {
                "total": data["total"],
                "correct": data["correct"],
                "accuracy_pct": round(data["correct"] / data["total"] * 100.0, 2)
                if data["total"] > 0
                else 0.0,
            }
            for s, data in sorted(by_scenario.items())
        },
    }


def calculate_route_completion(
    runs: list[dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Calculates route completion rate and spotter safety events across 20 runs."""
    total = len(runs)
    if total == 0:
        return {"data_origin": data_origin, "error": "No runs provided"}

    completed = sum(1 for r in runs if r.get("reached_destination", False))
    interventions = sum(r.get("spotter_interventions", 0) for r in runs)
    collisions = sum(r.get("collisions", 0) for r in runs)

    completion_rate = completed / total
    return {
        "data_origin": data_origin,
        "total_runs": total,
        "completed_runs": completed,
        "completion_rate_pct": round(completion_rate * 100.0, 2),
        "spotter_interventions": interventions,
        "collisions": collisions,
        "target_met": completion_rate >= 0.90 and collisions == 0,
    }


def calculate_latency_percentiles(
    samples_ms: list[float],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Calculates latency statistics and validates p95 against the 700 ms budget."""
    if not samples_ms:
        return {"data_origin": data_origin, "error": "No latency samples"}

    sorted_ms = sorted(samples_ms)
    n = len(sorted_ms)

    def percentile(p: float) -> float:
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_ms[int(k)]
        d0 = sorted_ms[int(f)] * (c - k)
        d1 = sorted_ms[int(c)] * (k - f)
        return d0 + d1

    mean_val = sum(sorted_ms) / n
    p50 = percentile(50.0)
    p90 = percentile(90.0)
    p95 = percentile(95.0)

    return {
        "data_origin": data_origin,
        "sample_count": n,
        "mean_ms": round(mean_val, 2),
        "median_ms": round(p50, 2),
        "p90_ms": round(p90, 2),
        "p95_ms": round(p95, 2),
        "budget_limit_ms": 700.0,
        "target_met": p95 <= 700.0,
    }


def calculate_escalation_accuracy(
    trials: list[dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Calculates recall and precision of STOP_AND_ESCALATE in unsafe situations."""
    tp = 0  # Unsafe situation correctly escalated
    fp = 0  # Safe situation falsely escalated
    fn = 0  # Unsafe situation missed
    tn = 0  # Safe situation correctly handled without escalation

    for t in trials:
        is_unsafe = t.get("ground_truth", {}).get("safety_critical", False)
        escalated = t.get("execution", {}).get("system_action") == "STOP_AND_ESCALATE"

        if is_unsafe and escalated:
            tp += 1
        elif not is_unsafe and escalated:
            fp += 1
        elif is_unsafe and not escalated:
            fn += 1
        else:
            tn += 1

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    return {
        "data_origin": data_origin,
        "total_evaluated": len(trials),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "target_met": recall >= 0.90,
    }


def calculate_cloud_metrics(
    staged_sequences: list[dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Calculates cloud agent classification accuracy and false escalation rate across 30 sequences."""
    total = len(staged_sequences)
    if total == 0:
        return {"data_origin": data_origin, "error": "No staged sequences"}

    correct = 0
    false_escalations = 0

    for s in staged_sequences:
        gt_outcome = s.get("ground_truth_outcome")  # TEMPORARY, UNCERTAIN, LASTING
        pred_outcome = s.get("predicted_outcome")
        if gt_outcome == pred_outcome:
            correct += 1

        # False escalation: sending approval request to facilities when blockage was temporary
        escalated_to_facilities = s.get("escalated_to_facilities", False)
        if gt_outcome == "TEMPORARY" and escalated_to_facilities:
            false_escalations += 1

    accuracy = correct / total
    return {
        "data_origin": data_origin,
        "total_sequences": total,
        "correct_classifications": correct,
        "accuracy_pct": round(accuracy * 100.0, 2),
        "false_escalations_to_facilities": false_escalations,
        "target_met": accuracy >= 0.80 and false_escalations <= 1,
    }


def calculate_cool_performance(
    config_runs: dict[str, dict[str, Any]],
    data_origin: DataOrigin = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    """Computes comparative throughput, latency, and cost per 1000 frames for COOL benchmark.

    Expected config_runs format:
    {
        'config_a': {'name': 'c7g.large + COOL', 'hourly_rate': 0.0723, 'latencies_ms': [...], 'total_frames': 300, 'total_time_s': ...},
        'config_b': {'name': 'c7g.large + stock', 'hourly_rate': 0.0723, 'latencies_ms': [...], 'total_frames': 300, 'total_time_s': ...},
        'config_c': {'name': 'c7i.large + stock', 'hourly_rate': 0.0890, 'latencies_ms': [...], 'total_frames': 300, 'total_time_s': ...}
    }
    """
    summary: dict[str, Any] = {"data_origin": data_origin, "configurations": {}}

    for key, data in config_runs.items():
        latencies = sorted(data.get("latencies_ms", []))
        n = len(latencies)
        total_time_s = data.get("total_time_s", 1.0)
        total_frames = data.get("total_frames", n)
        hourly_rate = data.get("hourly_rate", 0.0)

        p50 = latencies[int(0.50 * n)] if n else 0.0
        p95 = latencies[int(0.95 * n)] if n else 0.0
        fps = total_frames / total_time_s if total_time_s > 0 else 0.0

        # Cost per 1000 frames = (cost_per_second * seconds_for_1000_frames)
        cost_per_sec = hourly_rate / 3600.0
        seconds_for_1000 = (1000.0 / fps) if fps > 0 else 0.0
        cost_per_1000 = cost_per_sec * seconds_for_1000

        summary["configurations"][key] = {
            "name": data.get("name", key),
            "median_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "throughput_fps": round(fps, 2),
            "cost_per_1000_frames_usd": round(cost_per_1000, 6),
        }

    # Relative speedup
    if "config_a" in summary["configurations"] and "config_b" in summary["configurations"]:
        fps_a = summary["configurations"]["config_a"]["throughput_fps"]
        fps_b = summary["configurations"]["config_b"]["throughput_fps"]
        summary["speedup_a_vs_b_graviton"] = round(fps_a / fps_b, 2) if fps_b > 0 else 1.0

    return summary
