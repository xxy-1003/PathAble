"""Regression tests for the measured-data evidence boundary."""

import json
from pathlib import Path
import tempfile
import unittest

from measured_inputs import DATASETS, FIXTURE_FILES, file_sha256, load_measured_inputs
from run_evaluation_pipeline import FIXTURES_DIR, run_pipeline

TEST_TEMP_DIR = Path(__file__).resolve().parent / ".test-tmp"


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
                                            "benchmark_runs_checked": True},
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
                    for key, provider in (("config_a", "cool"), ("config_b", "stock"), ("config_c", "stock")):
                        config = rows[key]
                        config.update(provider=provider, input_manifest_sha256="test-manifest",
                                      model_sha256="test-model", latencies_ms=[20.0] * 300)
                elif name == "latency":
                    rows[0] += 1.0
                else:
                    rows[0]["test_only_marker"] = "not a physical trial"
                payload = {"metadata": {"data_origin": "PHYSICAL_MEASURED",
                                        "collection_id": "test-only"}, field: rows}
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
                                            "benchmark_runs_checked": True},
                        "datasets": entries}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = run_pipeline("measured", data_dir=directory)
            self.assertIn("PHYSICAL_MEASURED", report)
            self.assertIn("Evidence reviewed by", report)


if __name__ == "__main__":
    unittest.main()
