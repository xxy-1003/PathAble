"""Unit tests for PathAble evaluation metrics engine (Person 5)."""

import json
from pathlib import Path
import unittest

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


class MetricCalculationTests(unittest.TestCase):
    def test_detection_metrics(self):
        samples = [
            {"distance_m": 1.2, "true_positives": 9, "false_positives": 1, "false_negatives": 1},
            {"distance_m": 3.0, "true_positives": 5, "false_positives": 2, "false_negatives": 2},  # > 2.5m filtered
        ]
        res = calculate_detection_metrics(samples, data_origin="SYNTHETIC_FIXTURE", max_distance_m=2.5)
        self.assertEqual(res["data_origin"], "SYNTHETIC_FIXTURE")
        self.assertEqual(res["true_positives"], 9)
        self.assertEqual(res["false_positives"], 1)
        self.assertEqual(res["false_negatives"], 1)
        self.assertEqual(res["precision"], 0.9)
        self.assertEqual(res["recall"], 0.9)
        self.assertTrue(res["target_met"])

    def test_decision_accuracy_with_fixture(self):
        fixture_path = FIXTURES_DIR / "synthetic_scenario_trials.json"
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        trials = data["trials"]
        self.assertEqual(len(trials), 80)

        res = calculate_decision_accuracy(trials, data_origin="SYNTHETIC_FIXTURE")
        self.assertEqual(res["total_trials"], 80)
        self.assertGreaterEqual(res["accuracy_pct"], 85.0)
        self.assertTrue(res["target_met"])
        self.assertEqual(len(res["scenario_breakdown"]), 8)

    def test_route_completion_with_fixture(self):
        fixture_path = FIXTURES_DIR / "synthetic_route_trials.json"
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        runs = data["runs"]
        self.assertEqual(len(runs), 20)

        res = calculate_route_completion(runs, data_origin="SYNTHETIC_FIXTURE")
        self.assertEqual(res["total_runs"], 20)
        self.assertEqual(res["completed_runs"], 19)
        self.assertEqual(res["completion_rate_pct"], 95.0)
        self.assertEqual(res["collisions"], 0)
        self.assertTrue(res["target_met"])

    def test_latency_percentiles_with_fixture(self):
        fixture_path = FIXTURES_DIR / "synthetic_latency_samples.json"
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        samples = data["samples_ms"]

        res = calculate_latency_percentiles(samples, data_origin="SYNTHETIC_FIXTURE")
        self.assertEqual(res["sample_count"], len(samples))
        self.assertLess(res["p95_ms"], 700.0)
        self.assertTrue(res["target_met"])

    def test_escalation_accuracy(self):
        trials = [
            {"ground_truth": {"safety_critical": True}, "execution": {"system_action": "STOP_AND_ESCALATE"}},
            {"ground_truth": {"safety_critical": True}, "execution": {"system_action": "STOP_AND_ESCALATE"}},
            {"ground_truth": {"safety_critical": True}, "execution": {"system_action": "CONTINUE"}},
            {"ground_truth": {"safety_critical": False}, "execution": {"system_action": "CONTINUE"}},
        ]
        res = calculate_escalation_accuracy(trials, data_origin="SYNTHETIC_FIXTURE")
        self.assertEqual(res["true_positives"], 2)
        self.assertEqual(res["false_negatives"], 1)
        self.assertEqual(res["recall"], 0.6667)

    def test_cloud_metrics_with_fixture(self):
        fixture_path = FIXTURES_DIR / "synthetic_cloud_sequences.json"
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        seqs = data["sequences"]

        res = calculate_cloud_metrics(seqs, data_origin="SYNTHETIC_FIXTURE")
        self.assertEqual(res["total_sequences"], 30)
        self.assertEqual(res["accuracy_pct"], 100.0)
        self.assertEqual(res["false_escalations_to_facilities"], 0)
        self.assertTrue(res["target_met"])

    def test_cool_performance_with_fixture(self):
        fixture_path = FIXTURES_DIR / "synthetic_cool_benchmarks.json"
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        configs = data["configurations"]

        res = calculate_cool_performance(configs, data_origin="SYNTHETIC_FIXTURE")
        self.assertIn("config_a", res["configurations"])
        self.assertIn("config_b", res["configurations"])
        self.assertIn("config_c", res["configurations"])
        self.assertGreater(res["speedup_a_vs_b_graviton"], 1.0)
        self.assertGreater(res["configurations"]["config_a"]["throughput_fps"], 0.0)
        self.assertGreater(res["configurations"]["config_a"]["cost_per_1000_frames_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
