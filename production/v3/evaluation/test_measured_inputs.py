"""Regression tests for the measured-data evidence boundary."""

import json
from pathlib import Path
import tempfile
import unittest

from measured_inputs import DATASETS, FIXTURE_FILES, _checked_file, file_sha256, load_measured_inputs
from recorded_benchmarks import load_recorded_benchmarks
from run_evaluation_pipeline import FIXTURES_DIR, run_pipeline

TEST_TEMP_DIR = Path(__file__).resolve().parent / ".test-tmp"


def native_record(provider):
    """Generated native-format object for code tests; never physical evidence."""
    return {"schema_version": 1, "status": "complete", "dataset_label": "recorded",
            "fixed_input_count": 300, "provider": provider,
            "dataset_manifest_sha256": "a" * 64, "model": {"sha256": "b" * 64},
            "input_files": [{"sha256": "c" * 64, "path": f"test_{index}.jpg"} for index in range(300)],
            "environment": {"instance_type": "test-graviton", "ami_id": "test-ami",
                            "architecture": "aarch64", "provider_evidence": {"verified": True}},
            "protocol": {"warmup_runs": 3, "measured_runs": 5, "same_input_order_each_run": True},
            "cost_assumptions": {"currency": "USD", "ec2_hourly_usd": None, "marketplace_hourly_usd": None},
            "runs": [{"phase": phase, "completed": True, "frame_count": 300, "wall_s": 6.0,
                      "latency_ms": [20.0] * 300, "outputs": [{} for _ in range(300)]}
                     for phase, count in (("warmup", 3), ("measured", 5)) for _ in range(count)]}


class MeasuredDataGateTests(unittest.TestCase):
    def test_measured_mode_requires_data_and_does_not_write_report(self):
        TEST_TEMP_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp:
            output = Path(temp) / "submission.md"
            output.write_text("existing submission placeholder", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires --data-dir"):
                run_pipeline("measured", output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing submission placeholder")

    def test_bundled_fixture_directory_cannot_be_measured(self):
        with self.assertRaisesRegex(ValueError, "separate existing directory"):
            load_measured_inputs(FIXTURES_DIR, FIXTURES_DIR)

    def test_human_review_record_is_required(self):
        TEST_TEMP_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp:
            directory = Path(temp)
            manifest = {"schema_version": 1, "data_origin": "PHYSICAL_MEASURED",
                        "collection": {"collection_id": "test-only", "site": "test-only",
                                       "recorded_by": "test-only",
                                       "recorded_at_utc": "2026-10-24T00:00:00Z"},
                        "datasets": {}}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "human evidence review"):
                load_measured_inputs(directory, FIXTURES_DIR)

    def test_renamed_fixture_with_changed_metadata_is_rejected(self):
        TEST_TEMP_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp:
            directory = Path(temp)
            entries = {}
            for name, (field, _) in DATASETS.items():
                source = directory / f"{name}_trial_log.txt"
                source.write_text("test-only source marker", encoding="utf-8")
                fixture = json.loads((FIXTURES_DIR / FIXTURE_FILES[name]).read_text(encoding="utf-8"))
                payload = {"metadata": {"data_origin": "PHYSICAL_MEASURED",
                                        "collection_id": "test-only"}, field: fixture[field]}
                path = directory / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                entries[name] = {"file": path.name, "sha256": file_sha256(path),
                                 "evidence": [{"file": source.name, "sha256": file_sha256(source)}]}
            manifest = {"schema_version": 1, "data_origin": "PHYSICAL_MEASURED",
                        "collection": {"collection_id": "test-only", "site": "test-only",
                                       "recorded_by": "test-only",
                                       "recorded_at_utc": "2026-10-24T00:00:00Z"},
                        "evidence_review": {"reviewed_by": "test-only", "reviewed_at_utc": "2026-10-24T00:00:00Z",
                                            "source_files_checked": True, "labels_checked": True,
                                            "benchmark_runs_checked": True,
                                            "calibration_measurements_checked": True, "no_simulated_outputs": True},
                        "datasets": entries}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bundled synthetic fixture values"):
                load_measured_inputs(directory, FIXTURES_DIR)

    def test_synthetic_mode_omits_submission_claims(self):
        report = run_pipeline("synthetic")
        self.assertIn("SYNTHETIC_FIXTURE", report)
        self.assertNotIn("MEASURED", report)
        self.assertNotIn("PASS", report)
        self.assertNotIn("speedup", report.lower())

    def test_declared_package_uses_separate_inputs(self):
        """Test the loader wiring only; this generated package is not trial evidence."""
        TEST_TEMP_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp:
            directory = Path(temp)
            entries = {}
            for name, (field, _) in DATASETS.items():
                source = directory / f"{name}_test_only_source.log"
                source.write_text("GENERATED UNIT TEST DATA; NOT PHYSICAL EVIDENCE", encoding="utf-8")
                fixture = json.loads((FIXTURES_DIR / FIXTURE_FILES[name]).read_text(encoding="utf-8"))
                rows = fixture[field]
                if name == "cool":
                    rows = {}
                    raw_evidence = []
                    for key, provider in (("config_a", "cool"), ("config_b", "stock")):
                        raw = directory / f"{key}_run.json"
                        raw.write_text(json.dumps(native_record(provider)), encoding="utf-8")
                        reference = {"file": raw.name, "sha256": file_sha256(raw)}
                        rows[key] = reference
                        raw_evidence.append(reference)
                elif name == "latency":
                    rows[0] += 1.0
                else:
                    rows[0]["test_only_marker"] = "not a physical trial"
                payload = {"metadata": {"data_origin": "PHYSICAL_MEASURED",
                                        "collection_id": "test-only"}, field: rows}
                if name == "latency":
                    payload["metadata"]["latency_scope"] = "capture_to_audible_speech"
                path = directory / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                entries[name] = {"file": path.name, "sha256": file_sha256(path),
                                 "evidence": (raw_evidence if name == "cool" else
                                              [{"file": source.name, "sha256": file_sha256(source)}])}
            manifest = {"schema_version": 1, "data_origin": "PHYSICAL_MEASURED",
                        "collection": {"collection_id": "test-only", "site": "test-only",
                                       "recorded_by": "test-only",
                                       "recorded_at_utc": "2026-10-24T00:00:00Z"},
                        "evidence_review": {"reviewed_by": "test-only", "reviewed_at_utc": "2026-10-24T00:00:00Z",
                                            "source_files_checked": True, "labels_checked": True,
                                            "benchmark_runs_checked": True,
                                            "calibration_measurements_checked": True, "no_simulated_outputs": True},
                        "datasets": entries}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = run_pipeline("measured", data_dir=directory)
            self.assertIn("PHYSICAL_MEASURED", report)
            self.assertIn("Evidence reviewed by", report)
            self.assertIn("Unavailable (rates missing)", report)


class RecordedBenchmarkTests(unittest.TestCase):
    def load_pair(self, change=None):
        TEST_TEMP_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp:
            directory = Path(temp)
            references, paths = {}, set()
            for key, provider in (("config_a", "cool"), ("config_b", "stock")):
                record = native_record(provider)
                if change and key == "config_b":
                    change(record)
                path = directory / f"{key}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                references[key] = {"file": path.name, "sha256": file_sha256(path)}
                paths.add(path.resolve())
            return load_recorded_benchmarks(directory.resolve(), references, _checked_file, paths)

    def test_native_timings_are_used_and_missing_prices_remain_unavailable(self):
        result = self.load_pair()
        self.assertEqual(result["configurations"]["config_a"]["throughput_fps"], 50.0)
        self.assertIsNone(result["configurations"]["config_a"]["cost_per_1000_frames_usd"])

    def test_synthetic_native_records_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete recorded"):
            self.load_pair(lambda record: record.update(dataset_label="synthetic"))

    def test_mismatched_model_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "identical inputs"):
            self.load_pair(lambda record: record["model"].update(sha256="d" * 64))

    def test_mismatched_graviton_hardware_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same instance type"):
            self.load_pair(lambda record: record["environment"].update(instance_type="other-graviton"))

    def test_incomplete_raw_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete raw"):
            self.load_pair(lambda record: record["runs"][-1].update(completed=False))

    def test_supplied_summary_cannot_override_raw_timings(self):
        result = self.load_pair(lambda record: record.update(
            summary={"median_run_throughput_fps": 999999, "cost_per_1000_frames_usd": 0}))
        self.assertEqual(result["configurations"]["config_b"]["throughput_fps"], 50.0)
        self.assertIsNone(result["configurations"]["config_b"]["cost_per_1000_frames_usd"])

    def test_explicit_zero_marketplace_rate_is_supported(self):
        result = self.load_pair(lambda record: record["cost_assumptions"].update(
            ec2_hourly_usd=0.1, marketplace_hourly_usd=0.0))
        self.assertGreater(result["configurations"]["config_b"]["cost_per_1000_frames_usd"], 0)


if __name__ == "__main__":
    unittest.main()
