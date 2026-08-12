"""Unit tests for scripts/run_ves_problem.py (generic multi-slice adapter)."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_ves_problem.py"
SPEC = importlib.util.spec_from_file_location("ves_problem_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


@dataclasses.dataclass(frozen=True)
class FakeSliceResult:
    run_id: str
    dataset_name: str
    generator: str
    status: str
    drafts: int
    improves: int
    best_code: str | None
    best_candidate_id: str | None
    rejected: int
    run_dir: Path
    records: tuple = ()
    candidates: tuple = ()
    data_contract: dict | None = None
    metrics: dict | None = None

    def to_summary(self) -> dict:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "task": "slice",
            "dataset": self.dataset_name,
            "generator": self.generator,
            "status": self.status,
            "drafts": self.drafts,
            "improves": self.improves,
            "best_candidate_id": self.best_candidate_id,
            "rejected": self.rejected,
            "data_contract": self.data_contract,
            **{
                f"best_{key}": value
                for key, value in (self.metrics or {}).items()
            },
        }


@dataclasses.dataclass(frozen=True)
class FakeApplyResult:
    status: str
    run_id: str
    run_dir: Path
    predictions_path: Path | None
    code_sha256: str
    data_sha256: dict
    predictions_sha256: str | None
    stdout_log: Path
    stderr_log: Path
    runner: str
    docker_image: str | None = None
    docker_digest: str | None = None
    data_contract: dict | None = None


def install_fake_slice(
    name: str,
    *,
    status: str = "verified",
    metrics: dict | None = None,
    with_search: bool = True,
    with_apply: bool = True,
    needs_host: bool = True,
    verified_metrics: list[str] | None = None,
    missing_artifact: str | None = None,
    tamper_best: bool = False,
    apply_fail: bool = False,
) -> None:
    """Inject a fake ``ves_modeling.<name>`` package into sys.modules."""
    counter = {"n": 0}
    pkg = types.ModuleType("ves_modeling")
    pkg.__path__ = []
    mod = types.ModuleType(f"ves_modeling.{name}")
    mod.API_SCHEMA_VERSION = "1.0"

    def capabilities() -> dict:
        return {
            "api_schema_version": "1.0",
            "operations": [f"run_{name}_search", f"apply_{name}_solution"],
            "verified_metrics": verified_metrics or list((metrics or {}).keys()),
            "data_contract": {"slice": name},
        }

    mod.capabilities = capabilities

    def make_run_dir(workspace, run_id) -> Path:
        workspace_path = Path(workspace) if workspace else Path.cwd() / "runs"
        workspace_path.mkdir(parents=True, exist_ok=True)
        run_dir = workspace_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    if with_search:
        def run_slice_search(
            public_dir,
            host_dir=None,
            *,
            drafts=2,
            improves=3,
            workspace=None,
            generator="mock",
            dataset_name="slice",
            fixture_dir=None,
            fallback_code=None,
            image="ves-modeling-runner:0.1",
            image_digest=None,
            timeout_seconds=900.0,
            split_metadata=None,
            **kwargs,
        ):
            counter["n"] += 1
            run_id = f"fake-{name}-{counter['n']:06d}"
            run_dir = make_run_dir(workspace, run_id)
            best_code = "print('best')\n" if status == "verified" else None
            if not (status == "verified" and missing_artifact == "best_solution"):
                (run_dir / "best_solution.py").write_text(
                    ("TAMPERED\n" if tamper_best else best_code or ""),
                    encoding="utf-8",
                )
            summary = {
                "run_id": run_id,
                "task": name,
                "status": status,
                "best_candidate_id": "cand-1" if status == "verified" else None,
                "rejected": 0,
            }
            if not (status == "verified" and missing_artifact == "summary"):
                (run_dir / "summary.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )
            return FakeSliceResult(
                run_id=run_id,
                dataset_name=dataset_name,
                generator=generator,
                status=status,
                drafts=drafts,
                improves=improves,
                best_code=best_code,
                best_candidate_id="cand-1" if status == "verified" else None,
                rejected=0,
                run_dir=run_dir,
                data_contract={"slice": name},
                metrics=metrics or {},
            )

        run_slice_search.__name__ = f"run_{name}_search"
        setattr(mod, f"run_{name}_search", run_slice_search)

    if with_apply:
        def apply_slice_solution(
            solution,
            public_dir,
            *,
            workspace=None,
            trusted_code=False,
            image="ves-modeling-runner:0.1",
            image_digest=None,
            timeout_seconds=900.0,
            fail_apply=apply_fail,
            **kwargs,
        ):
            if fail_apply:
                raise RuntimeError("candidate artifact_missing")
            run_dir = make_run_dir(workspace, f"apply-{name}")
            candidate_dir = run_dir / "candidate"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            predictions = candidate_dir / "predictions.json"
            predictions.write_text(json.dumps({"values": [1, 2, 3]}), encoding="utf-8")
            (run_dir / "summary.json").write_text(
                json.dumps({"status": "produced_unverified"}), encoding="utf-8"
            )
            (candidate_dir / "stdout.log").write_text("", encoding="utf-8")
            (candidate_dir / "stderr.log").write_text("", encoding="utf-8")
            from hashlib import sha256

            return FakeApplyResult(
                status="produced_unverified",
                run_id=f"apply-{name}",
                run_dir=run_dir,
                predictions_path=predictions,
                code_sha256=sha256(solution.encode()).hexdigest(),
                data_sha256={},
                predictions_sha256=sha256(predictions.read_bytes()).hexdigest(),
                stdout_log=candidate_dir / "stdout.log",
                stderr_log=candidate_dir / "stderr.log",
                runner="local" if trusted_code else "docker",
                data_contract={"slice": name},
            )

        apply_slice_solution.__name__ = f"apply_{name}_solution"
        setattr(mod, f"apply_{name}_solution", apply_slice_solution)

    sys.modules["ves_modeling"] = pkg
    sys.modules[f"ves_modeling.{name}"] = mod


def write_classification_data(root: Path) -> tuple[Path, Path]:
    public = root / "public"
    host = root / "host"
    public.mkdir(parents=True, exist_ok=True)
    host.mkdir(parents=True, exist_ok=True)
    (public / "train.csv").write_text(
        "target,f1,f2\nno,1,2\nyes,2,3\nno,3,4\nyes,4,5\n", encoding="utf-8"
    )
    (public / "test_features.csv").write_text(
        "f1,f2\n5,6\n6,7\n", encoding="utf-8"
    )
    (host / "hidden_test_labels.csv").write_text(
        "target\nno\nyes\n", encoding="utf-8"
    )
    return public, host


def write_optimization_data(root: Path) -> Path:
    public = root / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "problem.json").write_text(
        json.dumps({"sense": "min", "variables": [], "constraints": []}),
        encoding="utf-8",
    )
    return public


class RunVESProblemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()
        for name in list(sys.modules):
            if name.startswith("ves_modeling"):
                sys.modules.pop(name, None)

    def _main(self, argv: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return adapter.main(argv)

    def test_list_slices_covers_catalog(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = adapter.main(["--list-slices"])
        self.assertEqual(code, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), len(adapter.SLICE_CATALOG))
        self.assertTrue(any(line.startswith("optimization") for line in lines))
        self.assertTrue(any(line.startswith("classification") for line in lines))

    def test_classification_verified_manifest(self) -> None:
        install_fake_slice(
            "classification",
            metrics={"accuracy": 0.92, "macro_f1": 0.90},
            verified_metrics=["accuracy", "macro_f1"],
        )
        public, host = write_classification_data(self.root)
        manifest = adapter.run_ves_problem(
            "classification", public, host, workspace=self.root / "ws"
        )
        self.assertEqual(manifest["schema_version"], "1.1")
        self.assertEqual(manifest["slice"], "classification")
        self.assertEqual(manifest["result"]["status"], "verified")
        self.assertEqual(manifest["result"]["metrics"]["accuracy"], 0.92)
        self.assertEqual(manifest["result"]["metrics"]["macro_f1"], 0.90)
        self.assertEqual(manifest["data_contract"]["slice"], "classification")
        self.assertEqual(manifest["backend"]["api_schema_version"], "1.0")
        self.assertTrue(Path(manifest["artifacts"]["best_solution"]).is_file())
        self.assertNotIn("best_code", manifest["artifacts"])
        self.assertIn("best_code_sha256", manifest["provenance"])

    def test_optimization_search_without_host_dir(self) -> None:
        install_fake_slice(
            "optimization",
            metrics={"objective": 42.0},
            verified_metrics=["objective"],
            needs_host=False,
        )
        public = write_optimization_data(self.root)
        manifest = adapter.run_ves_problem(
            "optimization", public, workspace=self.root / "ws_opt"
        )
        self.assertEqual(manifest["result"]["status"], "verified")
        self.assertEqual(manifest["result"]["metrics"]["objective"], 42.0)
        self.assertIsNone(manifest["task"]["host_dir"])

    def test_missing_host_dir_fails_closed(self) -> None:
        install_fake_slice("classification")
        public, _host = write_classification_data(self.root)
        with self.assertRaises(adapter.VESValidationError):
            adapter.run_ves_problem("classification", public)
        self.assertEqual(
            self._main(
                ["--slice", "classification", "--public-dir", str(public)]
            ),
            1,
        )

    def test_public_leak_fails_closed(self) -> None:
        install_fake_slice("classification")
        public, host = write_classification_data(self.root)
        (public / "hidden_test_labels.csv").write_text(
            "target\nno\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "leak"):
            adapter.run_ves_problem("classification", public, host)

    def test_host_inside_public_rejected(self) -> None:
        install_fake_slice("classification")
        public, _host = write_classification_data(self.root)
        nested = public / "host_nested"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "hidden_test_labels.csv").write_text(
            "target\nno\nyes\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "disjoint"):
            adapter.run_ves_problem("classification", public, nested)

    def test_public_inside_host_rejected(self) -> None:
        install_fake_slice("classification")
        public, host = write_classification_data(self.root)
        nested_public = host / "public_nested"
        nested_public.mkdir(parents=True, exist_ok=True)
        (nested_public / "train.csv").write_text(
            "target,f1,f2\n0,1,2\n1,3,4\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "disjoint"):
            adapter.run_ves_problem("classification", nested_public, host)

    def test_unknown_slice_fails_closed(self) -> None:
        public, _host = write_classification_data(self.root)
        with self.assertRaises(adapter.VESValidationError):
            adapter.run_ves_problem("no_such_slice", public)

    def test_backend_missing_exit2(self) -> None:
        install_fake_slice("classification", with_search=False)
        public, host = write_classification_data(self.root)
        self.assertEqual(
            self._main(
                [
                    "--slice", "classification",
                    "--public-dir", str(public),
                    "--host-dir", str(host),
                ]
            ),
            2,
        )

    def test_no_verified_exit3(self) -> None:
        install_fake_slice(
            "classification", status="no_verified", metrics={},
            verified_metrics=["accuracy"],
        )
        public, host = write_classification_data(self.root)
        output = self.root / "nv.json"
        code = self._main(
            [
                "--slice", "classification",
                "--public-dir", str(public),
                "--host-dir", str(host),
                "--workspace", str(self.root / "ws_nv"),
                "--output", str(output),
            ]
        )
        self.assertEqual(code, 3)
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"]["status"], "no_verified")
        self.assertIsNone(manifest["provenance"]["best_code_sha256"])

    def test_apply_produced_unverified_exit5(self) -> None:
        install_fake_slice("classification")
        public, _host = write_classification_data(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        output = self.root / "apply.json"
        workspace = self.root / "ws_apply"
        code = self._main(
            [
                "--slice", "classification",
                "--apply",
                "--public-dir", str(public),
                "--solution", str(solution),
                "--workspace", str(workspace),
                "--output", str(output),
                "--trusted-code",
            ]
        )
        self.assertEqual(code, 5)
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["operation"], "apply")
        self.assertEqual(manifest["result"]["status"], "produced_unverified")
        self.assertNotIn("metrics", manifest["result"])
        self.assertTrue(Path(manifest["artifacts"]["predictions"]).is_file())
        self.assertTrue(
            Path(manifest["artifacts"]["run_dir"]).is_relative_to(workspace)
        )
        self.assertEqual(manifest["result"]["runner"], "local")

    def test_apply_failure_exit4(self) -> None:
        install_fake_slice("classification", apply_fail=True)
        public, _host = write_classification_data(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        self.assertEqual(
            self._main(
                [
                    "--slice", "classification",
                    "--apply",
                    "--public-dir", str(public),
                    "--solution", str(solution),
                    "--workspace", str(self.root / "ws_apply_fail"),
                    "--trusted-code",
                ]
            ),
            4,
        )

    def test_verified_missing_artifact_exit4(self) -> None:
        install_fake_slice("classification", missing_artifact="summary")
        public, host = write_classification_data(self.root)
        self.assertEqual(
            self._main(
                [
                    "--slice", "classification",
                    "--public-dir", str(public),
                    "--host-dir", str(host),
                    "--workspace", str(self.root / "ws_missing"),
                ]
            ),
            4,
        )

    def test_verified_tampered_best_code_exit4(self) -> None:
        install_fake_slice("classification", tamper_best=True)
        public, host = write_classification_data(self.root)
        self.assertEqual(
            self._main(
                [
                    "--slice", "classification",
                    "--public-dir", str(public),
                    "--host-dir", str(host),
                    "--workspace", str(self.root / "ws_tamper"),
                ]
            ),
            4,
        )

    def test_apply_missing_backend_exit2(self) -> None:
        install_fake_slice("classification", with_apply=False)
        public, _host = write_classification_data(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        self.assertEqual(
            self._main(
                [
                    "--slice", "classification",
                    "--apply",
                    "--public-dir", str(public),
                    "--solution", str(solution),
                    "--trusted-code",
                ]
            ),
            2,
        )

    def test_check_only_reports_capability(self) -> None:
        install_fake_slice("classification")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = adapter.main(
                ["--slice", "classification", "--check-only"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["available"])
        self.assertEqual(payload["verified_metrics"], [])


if __name__ == "__main__":
    unittest.main()
