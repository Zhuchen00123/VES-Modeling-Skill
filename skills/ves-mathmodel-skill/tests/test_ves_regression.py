#!/usr/bin/env python3
"""Unit tests for scripts/run_ves_regression.py.

Uses temporary directories and a fake public ``ves_modeling.regression``
module injected into ``sys.modules``; no real ves-modeling install and no
Docker are required.
"""

from __future__ import annotations

import dataclasses
import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_ves_regression.py"
SPEC = importlib.util.spec_from_file_location("ves_regression_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


@dataclasses.dataclass(frozen=True)
class FakeRegressionSearchResult:
    run_id: str
    dataset_name: str
    generator: str
    status: str
    drafts: int
    improves: int
    best_code: str | None
    best_candidate_id: str | None
    best_rmse: float | None
    best_mae: float | None
    rejected: int
    run_dir: Path
    records: tuple = ()
    candidates: tuple = ()
    data_contract: dict | None = None

    def to_summary(self) -> dict:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "task": "regression",
            "dataset": self.dataset_name,
            "generator": self.generator,
            "status": self.status,
            "drafts": self.drafts,
            "improves": self.improves,
            "best_candidate_id": self.best_candidate_id,
            "best_rmse": self.best_rmse,
            "best_mae": self.best_mae,
            "rejected": self.rejected,
            "candidates": [dict(item) for item in self.candidates],
            "data_contract": self.data_contract,
        }


@dataclasses.dataclass(frozen=True)
class FakeApplyRegressionResult:
    status: str
    run_id: str
    run_dir: Path
    candidate_dir: Path
    predictions_path: Path | None
    code_sha256: str
    data_sha256: dict
    predictions_sha256: str | None
    stdout_log: Path
    stderr_log: Path
    runner: str
    docker_image: str | None = None
    docker_digest: str | None = None
    timeout_seconds: float | None = None
    resources: dict | None = None
    data_contract: dict | None = None


def install_fake_backend(
    *,
    status: str = "verified",
    with_search: bool = True,
    with_apply: bool = True,
    apply_missing_predictions: bool = False,
    missing_search_param: str | None = None,
    missing_artifact: str | None = None,
    tamper_best: bool = False,
) -> None:
    """Inject a fake ``ves_modeling.regression`` package into sys.modules."""
    fake_run_counter = {"n": 0}
    pkg = types.ModuleType("ves_modeling")
    pkg.__path__ = []  # type: ignore[attr-defined]
    mod = types.ModuleType("ves_modeling.regression")
    mod.RegressionSearchResult = FakeRegressionSearchResult
    mod.ApplyRegressionResult = FakeApplyRegressionResult
    mod.API_SCHEMA_VERSION = "1.0"

    def capabilities() -> dict:
        return {
            "api_schema_version": "1.0",
            "operations": ["run_regression_search", "apply_regression_solution"],
            "apply_statuses": ["produced_unverified"],
            "verified_metrics": ["rmse", "mae"],
            "data_contract": {
                "target_column": {"default": "target", "customizable": True},
                "id_column": {"default": None},
                "row_order": ["input", "id"],
            },
        }

    mod.capabilities = capabilities

    if with_search:

        def run_regression_search(
            public_dir,
            host_dir,
            *,
            drafts=2,
            improves=3,
            workspace=None,
            generator="mock",
            dataset_name="regression",
            fixture_dir=None,
            fallback_code=None,
            image="ves-modeling-runner:0.1",
            timeout_seconds=900.0,
            image_digest=None,
            target_column="target",
            id_column=None,
            row_order="input",
            split_metadata=None,
        ):
            workspace_path = Path(workspace) if workspace else Path.cwd() / "runs"
            workspace_path.mkdir(parents=True, exist_ok=True)
            fake_run_counter["n"] += 1
            run_id = f"fake-run-{fake_run_counter['n']:06d}"
            run_dir = workspace_path / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            best_code = "print('best candidate')\n" if status == "verified" else None
            if not (status == "verified" and missing_artifact == "best_solution"):
                (run_dir / "best_solution.py").write_text(
                    ("TAMPERED\n" if tamper_best else best_code or ""),
                    encoding="utf-8",
                    newline="\n",
                )
            summary = {
                "run_id": run_id,
                "task": "regression",
                "dataset": dataset_name,
                "generator": generator,
                "status": status,
                "drafts": drafts,
                "improves": improves,
                "best_candidate_id": "cand-1" if status == "verified" else None,
                "best_rmse": 0.5 if status == "verified" else None,
                "best_mae": 0.4 if status == "verified" else None,
                "rejected": 1,
            }
            if not (status == "verified" and missing_artifact == "summary"):
                (run_dir / "summary.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )
            if not (status == "verified" and missing_artifact == "config"):
                (run_dir / "config.json").write_text(
                    json.dumps({"generator": generator}), encoding="utf-8"
                )
            return FakeRegressionSearchResult(
                run_id=run_id,
                dataset_name=dataset_name,
                generator=generator,
                status=status,
                drafts=drafts,
                improves=improves,
                best_code=best_code,
                best_candidate_id="cand-1" if status == "verified" else None,
                best_rmse=0.5 if status == "verified" else None,
                best_mae=0.4 if status == "verified" else None,
                rejected=1,
                run_dir=run_dir,
                records=(),
                candidates=(),
                data_contract={
                    "target_column": target_column,
                    "id_column": id_column,
                    "row_order": row_order,
                    "test_rows": 3,
                },
            )

        mod.run_regression_search = run_regression_search

    if with_apply:
        apply_counter = {"n": 0}

        def apply_regression_solution(
            solution,
            public_dir,
            *,
            workspace=None,
            run_id=None,
            trusted_code=False,
            image="ves-modeling-runner:0.1",
            image_digest=None,
            timeout_seconds=900.0,
            docker_executable="docker",
            target_column="target",
            id_column=None,
            row_order="input",
        ):
            if apply_missing_predictions:
                raise RuntimeError("candidate artifact_missing")
            workspace_path = Path(workspace) if workspace else Path.cwd() / "runs"
            workspace_path.mkdir(parents=True, exist_ok=True)
            apply_counter["n"] += 1
            apply_run_id = run_id or f"apply-run-{apply_counter['n']:06d}"
            run_dir = workspace_path / apply_run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            candidate_dir = run_dir / "candidate"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            predictions = candidate_dir / "predictions.json"
            predictions.write_text(
                json.dumps({"predictions": [4.0, 5.0, 6.0]}),
                encoding="utf-8",
            )
            (candidate_dir / "summary.json").write_text(
                json.dumps({"status": "produced_unverified"}),
                encoding="utf-8",
            )
            (candidate_dir / "stdout.log").write_text("", encoding="utf-8")
            (candidate_dir / "stderr.log").write_text("", encoding="utf-8")
            from hashlib import sha256

            return FakeApplyRegressionResult(
                status="produced_unverified",
                run_id=apply_run_id,
                run_dir=run_dir,
                candidate_dir=candidate_dir,
                predictions_path=predictions,
                code_sha256=sha256(
                    solution.encode("utf-8")
                ).hexdigest(),
                data_sha256={
                    "public/train.csv": "abc",
                    "public/test_features.csv": "def",
                },
                predictions_sha256=sha256(
                    predictions.read_bytes()
                ).hexdigest(),
                stdout_log=candidate_dir / "stdout.log",
                stderr_log=candidate_dir / "stderr.log",
                runner="local" if trusted_code else "docker",
                docker_image=None if trusted_code else image,
                docker_digest=None if trusted_code else image_digest,
                data_contract={
                    "target_column": target_column,
                    "id_column": id_column,
                    "row_order": row_order,
                    "test_rows": 3,
                },
            )

        mod.apply_regression_solution = apply_regression_solution

    sys.modules["ves_modeling"] = pkg
    sys.modules["ves_modeling.regression"] = mod


def write_dataset(
    root: Path,
    *,
    with_id: bool = True,
) -> tuple[Path, Path]:
    """Create public/host dirs with a tiny consistent dataset."""
    public = root / "public"
    host = root / "host"
    public.mkdir(parents=True, exist_ok=True)
    host.mkdir(parents=True, exist_ok=True)

    header_id = "id,target,f1,f2" if with_id else "target,f1,f2"
    train_rows = (
        "1,1.0,1,2\n2,2.0,2,3\n3,3.0,3,4\n"
        if with_id
        else "1.0,1,2\n2.0,2,3\n3.0,3,4\n"
    )
    hidden_rows = (
        "4,4.0\n5,5.0\n6,6.0\n" if with_id else "4.0\n5.0\n6.0\n"
    )
    (public / "train.csv").write_text(
        header_id + "\n" + train_rows, encoding="utf-8"
    )
    (public / "test_features.csv").write_text(
        ("id,f1,f2\n" if with_id else "f1,f2\n") + "4,5\n5,6\n6,7\n",
        encoding="utf-8",
    )
    (host / "hidden_test_labels.csv").write_text(
        ("id,target\n" if with_id else "target\n") + hidden_rows,
        encoding="utf-8",
    )
    return public, host


class RunVESRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        install_fake_backend()

    def tearDown(self) -> None:
        self.tempdir.cleanup()
        sys.modules.pop("ves_modeling.regression", None)
        sys.modules.pop("ves_modeling", None)

    def _main(self, argv: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return adapter.main(argv)

    def test_verified_manifest_normal(self) -> None:
        public, host = write_dataset(self.root)
        workspace = self.root / "workspace"
        output = self.root / "manifest.json"
        manifest = adapter.run_ves_regression(
            public,
            host,
            workspace=workspace,
            output=output,
            dataset_name="cumcmA-Q1",
            generator="mock",
        )
        self.assertEqual(manifest["schema_version"], "1.1")
        self.assertEqual(manifest["operation"], "search")
        self.assertEqual(manifest["result"]["status"], "verified")
        self.assertEqual(manifest["result"]["candidate_id"], "cand-1")
        self.assertAlmostEqual(manifest["result"]["rmse"], 0.5)
        self.assertAlmostEqual(manifest["result"]["mae"], 0.4)
        self.assertTrue(output.is_file())
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8")), manifest
        )
        # no best_evidence / records / best_code content in the manifest
        self.assertNotIn("best_evidence", manifest)
        self.assertNotIn("records", manifest)
        self.assertNotIn("best_code", manifest["artifacts"])
        self.assertIn("best_solution", manifest["artifacts"])
        self.assertTrue(Path(manifest["artifacts"]["best_solution"]).is_file())
        self.assertIn("best_code_sha256", manifest["provenance"])
        self.assertIn("generated_utc", manifest["provenance"])
        self.assertEqual(
            set(manifest["provenance"]["files_sha256"]),
            {
                "public/train.csv",
                "public/test_features.csv",
                "host/hidden_test_labels.csv",
            },
        )
        self.assertEqual(
            manifest["data_contract"],
            {
                "target_column": "target",
                "id_column": None,
                "row_order": "input",
                "test_rows": 3,
            },
        )
        self.assertTrue(
            manifest["backend"]["capability"]["has_apply_regression_solution"]
        )
        self.assertEqual(manifest["backend"]["api_schema_version"], "1.0")

    def test_search_passes_data_contract_params(self) -> None:
        public, host = write_dataset(self.root)
        manifest = adapter.run_ves_regression(
            public,
            host,
            workspace=self.root / "ws_contract",
            target_column="target",
            id_column="id",
            row_order="id",
            split_metadata={"seed": 7},
        )
        self.assertEqual(
            manifest["data_contract"]["row_order"], "id"
        )
        self.assertEqual(
            manifest["data_contract"]["id_column"], "id"
        )
        self.assertEqual(
            manifest["provenance"]["generation_params"]["split_metadata"],
            {"seed": 7},
        )

    def test_apply_produced_unverified_exit5(self) -> None:
        public, _host = write_dataset(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        output = self.root / "apply_manifest.json"
        exit_code = self._main(
            [
                "--apply",
                "--public-dir",
                str(public),
                "--solution",
                str(solution),
                "--workspace",
                str(self.root / "ws_apply"),
                "--output",
                str(output),
                "--trusted-code",
            ]
        )
        self.assertEqual(exit_code, 5)
        self.assertTrue(output.is_file())
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "1.1")
        self.assertEqual(manifest["operation"], "apply")
        self.assertEqual(manifest["result"]["status"], "produced_unverified")
        self.assertNotIn("rmse", manifest["result"])
        self.assertNotIn("mae", manifest["result"])
        self.assertIsNotNone(manifest["result"]["predictions_sha256"])
        self.assertTrue(Path(manifest["artifacts"]["predictions"]).is_file())

    def test_apply_missing_solution_file_exit1(self) -> None:
        public, _host = write_dataset(self.root)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = adapter.main(
                [
                    "--apply",
                    "--public-dir",
                    str(public),
                    "--solution",
                    str(self.root / "no_such_solution.py"),
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("validation error", stderr.getvalue())

    def test_apply_leaked_labels_fail_closed(self) -> None:
        public, host = write_dataset(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        (public / "hidden_test_labels.csv").write_text(
            "target\n1.0\n", encoding="utf-8"
        )
        self.assertEqual(
            self._main(
                [
                    "--apply",
                    "--public-dir",
                    str(public),
                    "--solution",
                    str(solution),
                    "--trusted-code",
                ]
            ),
            1,
        )

    def test_apply_backend_missing_fails_closed(self) -> None:
        install_fake_backend(with_apply=False)
        public, _host = write_dataset(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        with self.assertRaises(adapter.VESBackendError):
            adapter.apply_ves_regression(
                solution, public, workspace=self.root / "ws_no_apply"
            )
        self.assertEqual(
            self._main(
                [
                    "--apply",
                    "--public-dir",
                    str(public),
                    "--solution",
                    str(solution),
                    "--trusted-code",
                ]
            ),
            2,
        )

    def test_apply_missing_predictions_exit4(self) -> None:
        install_fake_backend(apply_missing_predictions=True)
        public, _host = write_dataset(self.root)
        solution = self.root / "best_solution.py"
        solution.write_text("print('best')\n", encoding="utf-8")
        self.assertEqual(
            self._main(
                [
                    "--apply",
                    "--public-dir",
                    str(public),
                    "--solution",
                    str(solution),
                    "--trusted-code",
                ]
            ),
            4,
        )

    def test_capability_detects_apply_entry(self) -> None:
        public, host = write_dataset(self.root)
        capability = adapter._detect_backend()  # noqa: SLF001 - unit probe
        self.assertTrue(capability["has_apply_regression_solution"])
        self.assertTrue(capability["apply_signature_ok"])
        self.assertTrue(capability["has_capabilities"])
        self.assertEqual(capability["api_schema_version"], "1.0")
        self.assertEqual(
            capability["capabilities_snapshot"]["apply_statuses"],
            ["produced_unverified"],
        )
        install_fake_backend(with_apply=False)
        capability = adapter._detect_backend()
        self.assertFalse(capability["has_apply_regression_solution"])
        self.assertFalse(capability["apply_signature_ok"])

    def test_missing_required_file_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "train.csv").unlink()
        with self.assertRaises(adapter.VESValidationError):
            adapter.run_ves_regression(public, host)
        self.assertEqual(
            self._main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                    "--workspace",
                    str(self.root / "ws"),
                ]
            ),
            1,
        )

    def test_public_leak_hidden_labels_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "hidden_test_labels.csv").write_text(
            "target\n1.0\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "leak"):
            adapter.run_ves_regression(public, host)

    def test_feature_mismatch_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "test_features.csv").write_text(
            "id,f1,f9\n4,5,1\n5,6,1\n6,7,1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "feature columns mismatch"):
            adapter.run_ves_regression(public, host)

    def test_feature_order_mismatch_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "test_features.csv").write_text(
            "id,f2,f1\n4,5,1\n5,6,1\n6,7,1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "expected exact order"):
            adapter.run_ves_regression(public, host)

    def test_duplicate_column_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "test_features.csv").write_text(
            "id,f1,f1\n4,5,1\n5,6,1\n6,7,1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "duplicate column"):
            adapter.run_ves_regression(public, host)

    def test_blank_or_whitespace_column_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "test_features.csv").write_text(
            "id, ,f2\n4,5,1\n5,6,1\n6,7,1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "whitespace"):
            adapter.run_ves_regression(public, host)
        (public / "test_features.csv").write_text(
            "id,,f2\n4,5,1\n5,6,1\n6,7,1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "empty header"):
            adapter.run_ves_regression(public, host)

    def test_header_only_csv_fails_closed(self) -> None:
        public, host = write_dataset(self.root)
        (public / "train.csv").write_text(
            "id,target,f1,f2\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "at least one data row"):
            adapter.run_ves_regression(public, host)

    def test_host_leak_rejected(self) -> None:
        public, host = write_dataset(self.root)
        with self.assertRaisesRegex(adapter.VESValidationError, "host leak"):
            adapter.run_ves_regression(public, public)
        nested_host = public / "host_nested"
        nested_host.mkdir(parents=True, exist_ok=True)
        (nested_host / "hidden_test_labels.csv").write_text(
            "target\n1.0\n2.0\n3.0\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "host leak"):
            adapter.run_ves_regression(public, nested_host)

    def test_timeout_zero_rejected(self) -> None:
        public, host = write_dataset(self.root)
        with self.assertRaisesRegex(adapter.VESValidationError, "timeout"):
            adapter.run_ves_regression(public, host, timeout=0)
        self.assertEqual(
            self._main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                    "--timeout",
                    "0",
                ]
            ),
            1,
        )

    def test_verified_missing_artifact_exit4(self) -> None:
        install_fake_backend(missing_artifact="summary")
        public, host = write_dataset(self.root)
        self.assertEqual(
            self._main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                    "--workspace",
                    str(self.root / "ws_missing"),
                ]
            ),
            4,
        )

    def test_verified_tampered_best_code_exit4(self) -> None:
        install_fake_backend(tamper_best=True)
        public, host = write_dataset(self.root)
        self.assertEqual(
            self._main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                    "--workspace",
                    str(self.root / "ws_tamper"),
                ]
            ),
            4,
        )

    def test_fallback_code_missing_file_exit1(self) -> None:
        public, host = write_dataset(self.root)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = adapter.main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                    "--generator",
                    "llm",
                    "--fallback-code",
                    str(self.root / "no_such_fallback.py"),
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("validation error", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_row_order_requires_explicit_opt_in(self) -> None:
        public, host = write_dataset(self.root, with_id=False)
        with self.assertRaisesRegex(adapter.VESValidationError, "assume-row-order"):
            adapter.run_ves_regression(public, host)
        manifest = adapter.run_ves_regression(
            public,
            host,
            assume_row_order=True,
            workspace=self.root / "ws_roworder",
        )
        self.assertEqual(manifest["result"]["status"], "verified")

    def test_ambiguous_shared_columns_requires_opt_in(self) -> None:
        public, host = write_dataset(self.root)
        (public / "train.csv").write_text(
            "id,target,x,f1,f2\n1,1.0,10,1,2\n2,2.0,11,2,3\n3,3.0,12,3,4\n",
            encoding="utf-8",
        )
        (public / "test_features.csv").write_text(
            "id,x,f1,f2\n4,10,5,1\n5,11,6,1\n6,12,7,1\n", encoding="utf-8"
        )
        (host / "hidden_test_labels.csv").write_text(
            "id,x,target\n4,10,4.0\n5,11,5.0\n6,12,6.0\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.VESValidationError, "ambiguous row-order"):
            adapter.run_ves_regression(public, host)
        manifest = adapter.run_ves_regression(
            public,
            host,
            assume_row_order=True,
            workspace=self.root / "ws_ambiguous",
        )
        self.assertEqual(manifest["result"]["status"], "verified")

    def test_no_verified_is_not_success(self) -> None:
        install_fake_backend(status="no_verified")
        public, host = write_dataset(self.root)
        output = self.root / "no_verified_manifest.json"
        exit_code = self._main(
            [
                "--public-dir",
                str(public),
                "--host-dir",
                str(host),
                "--workspace",
                str(self.root / "ws_no_verified"),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(exit_code, 3)
        self.assertTrue(output.is_file())
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"]["status"], "no_verified")
        self.assertIsNone(manifest["result"]["rmse"])
        self.assertIsNone(manifest["result"]["mae"])
        self.assertIsNone(manifest["provenance"]["best_code_sha256"])

    def test_capability_missing_entry_point_fails_closed(self) -> None:
        install_fake_backend(with_search=False)
        public, host = write_dataset(self.root)
        with self.assertRaises(adapter.VESBackendError):
            adapter.run_ves_regression(public, host)
        self.assertEqual(
            self._main(
                [
                    "--public-dir",
                    str(public),
                    "--host-dir",
                    str(host),
                ]
            ),
            2,
        )

    def test_check_only_reports_capability(self) -> None:
        public, host = write_dataset(self.root)
        self.assertEqual(
            self._main(["--check-only"]),
            0,
        )
        install_fake_backend(with_search=False)
        self.assertEqual(
            self._main(["--check-only"]),
            2,
        )

    def test_fingerprint_stable(self) -> None:
        public, host = write_dataset(self.root)
        first = adapter.run_ves_regression(
            public, host, workspace=self.root / "ws1"
        )
        second = adapter.run_ves_regression(
            public, host, workspace=self.root / "ws2"
        )
        self.assertEqual(
            first["provenance"]["files_sha256"],
            second["provenance"]["files_sha256"],
        )
        self.assertEqual(
            first["provenance"]["best_code_sha256"],
            second["provenance"]["best_code_sha256"],
        )
        self.assertNotEqual(first["result"]["run_id"], second["result"]["run_id"])


if __name__ == "__main__":
    unittest.main()
