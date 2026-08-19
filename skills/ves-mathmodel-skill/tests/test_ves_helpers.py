import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Load ves_scaffold
scaffold_path = ROOT / "scripts" / "ves_scaffold.py"
scaffold_spec = importlib.util.spec_from_file_location("ves_scaffold", scaffold_path)
assert scaffold_spec and scaffold_spec.loader
ves_scaffold = importlib.util.module_from_spec(scaffold_spec)
scaffold_spec.loader.exec_module(ves_scaffold)

# Load render_ves_report
report_path = ROOT / "scripts" / "render_ves_report.py"
report_spec = importlib.util.spec_from_file_location("render_ves_report", report_path)
assert report_spec and report_spec.loader
render_ves_report = importlib.util.module_from_spec(report_spec)
report_spec.loader.exec_module(render_ves_report)


class VESHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ves_scaffold_registers_subproblem(self) -> None:
        dlog_path = self.root / "state" / "decision_log.json"
        dlog_path.parent.mkdir(parents=True, exist_ok=True)
        dlog_path.write_text("{}", encoding="utf-8")

        res = ves_scaffold.register_subproblem(
            qi="Q1",
            slice_name="forecasting",
            decision_log_path=dlog_path,
            description="重点物料周需求预测",
            create_dirs=True,
            cwd=self.root,
            extra_sets={"target_column": "demand", "time_column": "week"},
        )

        self.assertEqual(res["qi"], "Q1")
        self.assertEqual(res["slice"], "forecasting")
        self.assertTrue((self.root / "data" / "q1_public").is_dir())
        self.assertTrue((self.root / "data" / "q1_host").is_dir())

        # Check decision_log content
        dlog = json.loads(dlog_path.read_text(encoding="utf-8"))
        s2 = dlog["stages"]["2"]["sub_problems"]["Q1"]
        self.assertTrue(s2["ves_eligibility"])
        self.assertEqual(s2["ves_slice"], "forecasting")
        self.assertIn("target_column", s2["command_hint"])

        s3 = dlog["stages"]["3"]["selected_per_subproblem"]["Q1"]
        self.assertEqual(s3["execution_backend"], "ves")
        self.assertTrue(s3["verifier_compatible"])

    def test_render_ves_report_generates_md_and_syncs_dlog(self) -> None:
        manifest_path = self.root / "state" / "q1_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "task": {"slice": "forecasting", "dataset": "Q1_demand"},
            "result": {
                "status": "verified",
                "run_id": "run-20260819-001",
                "candidate_id": "cand-003",
                "metrics": {"rmse": 1.25, "wape": 0.082},
            },
            "artifacts": {
                "best_solution": str(self.root / "best_solution.py"),
                "run_dir": str(self.root / "ves_runs" / "q1_forecasting"),
            },
            "provenance": {
                "best_code_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            },
        }
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

        dlog_path = self.root / "state" / "decision_log.json"
        dlog_path.write_text("{}", encoding="utf-8")
        out_md = self.root / "results" / "Q1_ves_report.md"

        res = render_ves_report.generate_ves_report(
            manifest_path=manifest_path,
            qi="Q1",
            output_md=out_md,
            decision_log_path=dlog_path,
        )

        self.assertEqual(res["status"], "verified")
        self.assertEqual(res["metrics"]["rmse"], 1.25)
        self.assertTrue(out_md.is_file())

        md_text = out_md.read_text(encoding="utf-8")
        self.assertIn("1.2500", md_text)
        self.assertIn("VERIFIED", md_text)
        self.assertIn("run-20260819-001", md_text)

        # Check decision_log sync
        dlog = json.loads(dlog_path.read_text(encoding="utf-8"))
        q1_s5 = dlog["stages"]["5"]["sub_problems"]["Q1"]
        self.assertEqual(q1_s5["ves_status"], "verified")
        self.assertEqual(q1_s5["ves_metrics"]["wape"], 0.082)


if __name__ == "__main__":
    unittest.main()
