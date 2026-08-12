#!/usr/bin/env python3
"""Thin adapter between the ves-mathmodel-skill workflow and the VES host.

Only the public module ``ves_modeling.regression`` is imported, lazily, and
only its public entry points (``run_regression_search``,
``apply_regression_solution``, ``capabilities``) plus the public result
dataclasses are consumed.  Private implementations
(Verifier/Judge/SearchEngine/Runner/generator/runner) and demo code are never
imported.  The adapter performs fail-closed prechecks, writes a normalized
Evidence manifest atomically, and never treats ``status != "verified"`` as
search success evidence; ``apply`` success is ``produced_unverified`` and is
never evidence.

Exit codes:
    0  search completed and status == "verified"
    1  input/precheck error (missing files, leaked hidden labels, schema or
       row-order contract violations)
    2  backend unavailable or capability/signature mismatch
    3  search completed but status != "verified" (manifest still written)
    4  unexpected backend exception
    5  apply completed with status == "produced_unverified" (never evidence)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import math
import os
import sys
import tempfile
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.1"
MANIFEST_FILENAME = "ves_regression_manifest.json"
REQUIRED_RESULT_FIELDS = (
    "run_id",
    "dataset_name",
    "generator",
    "status",
    "drafts",
    "improves",
    "best_code",
    "best_candidate_id",
    "best_rmse",
    "best_mae",
    "rejected",
    "run_dir",
)
PASSED_ARGS = (
    "public_dir",
    "host_dir",
    "drafts",
    "improves",
    "workspace",
    "generator",
    "dataset_name",
    "fixture_dir",
    "fallback_code",
    "image",
    "timeout_seconds",
    "image_digest",
    "target_column",
    "id_column",
    "row_order",
    "split_metadata",
)
APPLY_REQUIRED_PARAMS = ("solution", "public_dir")


class VESValidationError(RuntimeError):
    """Input or precheck contract violation; CLI exit code 1."""


class VESBackendError(RuntimeError):
    """Backend unavailable or capability mismatch; CLI exit code 2."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_columns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise VESValidationError(f"CSV is empty (no header row): {path}") from exc
    seen: set[str] = set()
    for idx, col in enumerate(header):
        if col == "":
            raise VESValidationError(
                f"empty header cell at column {idx + 1}: {path}"
            )
        if col != col.strip():
            raise VESValidationError(
                f"column name has leading/trailing whitespace "
                f"at column {idx + 1} ({col!r}): {path}"
            )
        if col in seen:
            raise VESValidationError(
                f"duplicate column name {col!r}: {path}"
            )
        seen.add(col)
    return list(header)


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return sum(1 for _ in csv.reader(fh)) - 1  # minus header


def _detect_backend() -> dict[str, Any]:
    """Stable-symbol capability detection. Never hardcodes a package version."""
    capability: dict[str, Any] = {
        "available": False,
        "module": "ves_modeling.regression",
        "error": None,
        "has_run_regression_search": False,
        "search_signature_ok": False,
        "missing_search_params": [],
        "has_apply_regression_solution": False,
        "apply_signature_ok": False,
        "missing_apply_params": [],
        "has_capabilities": False,
        "api_schema_version": None,
        "capabilities_snapshot": None,
        "result_fields_ok": False,
        "missing_result_fields": [],
        "package_version": None,
    }
    try:
        module = importlib.import_module("ves_modeling.regression")
    except Exception as exc:  # noqa: BLE001 - report any import failure clearly
        capability["error"] = f"cannot import ves_modeling.regression: {exc}"
        return capability

    try:
        capability["package_version"] = importlib.metadata.version("ves-modeling")
    except Exception:  # noqa: BLE001 - metadata absence is not fatal
        capability["package_version"] = None

    search = getattr(module, "run_regression_search", None)
    if search is None:
        capability["error"] = "module has no run_regression_search"
        return capability
    capability["has_run_regression_search"] = True

    try:
        sig = inspect.signature(search)
        params = set(sig.parameters)
    except (TypeError, ValueError):
        params = set()
    missing = [name for name in PASSED_ARGS if name not in params]
    capability["missing_search_params"] = missing
    capability["search_signature_ok"] = not missing

    apply_fn = getattr(module, "apply_regression_solution", None)
    capability["has_apply_regression_solution"] = apply_fn is not None
    if apply_fn is not None:
        try:
            apply_params = set(inspect.signature(apply_fn).parameters)
        except (TypeError, ValueError):
            apply_params = set()
        missing_apply = [
            name for name in APPLY_REQUIRED_PARAMS if name not in apply_params
        ]
        capability["missing_apply_params"] = missing_apply
        capability["apply_signature_ok"] = not missing_apply
    else:
        capability["missing_apply_params"] = list(APPLY_REQUIRED_PARAMS)
        capability["apply_signature_ok"] = False

    caps = getattr(module, "capabilities", None)
    capability["has_capabilities"] = callable(caps)
    capability["api_schema_version"] = getattr(
        module, "API_SCHEMA_VERSION", None
    )
    try:
        caps_json = caps() if callable(caps) else None
        capability["capabilities_snapshot"] = (
            caps_json if isinstance(caps_json, dict) else None
        )
    except Exception:  # noqa: BLE001 - probing must never crash the check
        capability["capabilities_snapshot"] = None

    result_cls = getattr(module, "RegressionSearchResult", None)
    if result_cls is None:
        capability["error"] = "module has no RegressionSearchResult"
        return capability
    if is_dataclass(result_cls):
        known = {item.name for item in fields(result_cls)}
    else:
        try:
            known = set(inspect.signature(result_cls).parameters)
        except (TypeError, ValueError):
            known = set()
    missing_fields = [name for name in REQUIRED_RESULT_FIELDS if name not in known]
    capability["missing_result_fields"] = missing_fields
    capability["result_fields_ok"] = not missing_fields

    if missing or missing_fields:
        capability["error"] = (
            "capability mismatch: "
            f"missing search params={missing}, missing result fields={missing_fields}"
        )
    else:
        capability["available"] = True
    return capability


def _validate_inputs(
    public_dir: Path,
    host_dir: Path,
    *,
    assume_row_order: bool,
) -> dict[str, str]:
    """Fail-closed prechecks. Returns {relative_path: sha256}."""
    public_dir = public_dir.resolve()
    host_dir = host_dir.resolve()
    if host_dir == public_dir or public_dir in host_dir.parents:
        raise VESValidationError(
            "host_dir must not equal public_dir or live inside it "
            "(host leak)"
        )
    if not public_dir.is_dir():
        raise VESValidationError(f"public_dir is not a directory: {public_dir}")
    if not host_dir.is_dir():
        raise VESValidationError(f"host_dir is not a directory: {host_dir}")

    leaked = public_dir / "hidden_test_labels.csv"
    if leaked.is_file():
        raise VESValidationError(
            f"public_dir must not contain hidden_test_labels.csv (label leak): {leaked}"
        )

    required_public = ("train.csv", "test_features.csv")
    missing = [name for name in required_public if not (public_dir / name).is_file()]
    if missing:
        raise VESValidationError(
            f"public_dir missing required files: {', '.join(missing)}"
        )
    if not (host_dir / "hidden_test_labels.csv").is_file():
        raise VESValidationError(
            f"host_dir missing required file: hidden_test_labels.csv"
        )

    train_path = public_dir / "train.csv"
    test_path = public_dir / "test_features.csv"
    hidden_path = host_dir / "hidden_test_labels.csv"

    train_cols = _csv_columns(train_path)
    test_cols = _csv_columns(test_path)
    hidden_cols = _csv_columns(hidden_path)

    if "target" not in train_cols:
        raise VESValidationError("train.csv must contain a 'target' column")
    if "target" in test_cols:
        raise VESValidationError("test_features.csv must not contain a 'target' column")
    if "target" not in hidden_cols:
        raise VESValidationError(
            "hidden_test_labels.csv must contain a 'target' column"
        )

    expected_features = [col for col in train_cols if col != "target"]
    if test_cols != expected_features:
        raise VESValidationError(
            "feature columns mismatch between train.csv and test_features.csv; "
            f"expected exact order {expected_features}, got {test_cols}"
        )

    test_rows = _csv_row_count(test_path)
    hidden_rows = _csv_row_count(hidden_path)
    train_rows = _csv_row_count(train_path)
    if train_rows < 1 or test_rows < 1 or hidden_rows < 1:
        raise VESValidationError(
            "train.csv, test_features.csv and hidden_test_labels.csv must each "
            f"contain at least one data row (got train={train_rows}, "
            f"test={test_rows}, hidden={hidden_rows})"
        )
    if test_rows != hidden_rows:
        raise VESValidationError(
            "row-count contract violated: "
            f"test_features.csv has {test_rows} rows, "
            f"hidden_test_labels.csv has {hidden_rows} rows"
        )

    # Row-order / ID contract: verify by shared ID column when possible,
    # otherwise require an explicit opt-in (fail-closed).
    shared = (set(test_cols) & set(hidden_cols)) - {"target"}
    if shared:
        if len(shared) > 1:
            if not assume_row_order:
                raise VESValidationError(
                    "ambiguous row-order ID columns "
                    f"(shared={sorted(shared)}); "
                    "pass --assume-row-order to override"
                )
            # explicit opt-in: skip the ambiguous ID comparison and trust row order
        else:
            id_col = sorted(shared)[0]
            with test_path.open("r", encoding="utf-8", newline="") as fh:
                test_ids = [row[id_col] for row in csv.DictReader(fh)]
            with hidden_path.open("r", encoding="utf-8", newline="") as fh:
                hidden_ids = [row[id_col] for row in csv.DictReader(fh)]
            if test_ids != hidden_ids:
                raise VESValidationError(
                    f"row-order ID mismatch on column {id_col!r}: "
                    "test_features.csv and hidden_test_labels.csv are not aligned"
                )
    elif not assume_row_order:
        raise VESValidationError(
            "row order cannot be guaranteed: no shared ID column between "
            "test_features.csv and hidden_test_labels.csv; "
            "pass --assume-row-order (assume_row_order=True) to proceed"
        )

    return {
        "public/train.csv": _sha256(train_path),
        "public/test_features.csv": _sha256(test_path),
        "host/hidden_test_labels.csv": _sha256(hidden_path),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def run_ves_regression(
    public_dir: str | os.PathLike[str],
    host_dir: str | os.PathLike[str],
    *,
    workspace: str | os.PathLike[str] | None = None,
    output: str | os.PathLike[str] | None = None,
    dataset_name: str = "regression",
    drafts: int = 2,
    improves: int = 3,
    generator: str = "mock",
    fixture_dir: str | os.PathLike[str] | None = None,
    fallback_code: str | None = None,
    image: str = "ves-modeling-runner:0.1",
    image_digest: str | None = None,
    timeout: float = 900.0,
    target_column: str = "target",
    id_column: str | None = None,
    row_order: str = "input",
    split_metadata: dict[str, Any] | None = None,
    assume_row_order: bool = False,
) -> dict[str, Any]:
    """Run the VES regression search and return the normalized manifest dict.

    Raises VESValidationError (exit 1) or VESBackendError (exit 2) on
    precheck/capability failures; a completed but unverified search returns a
    manifest with ``result.status != "verified"`` (CLI treats it as exit 3).
    """
    if sys.version_info < (3, 11):
        raise VESValidationError(
            f"Python >= 3.11 required, got {sys.version_info.major}."
            f"{sys.version_info.minor}"
        )
    if generator not in ("mock", "llm"):
        raise VESValidationError(
            f"generator must be 'mock' or 'llm', got {generator!r}"
        )
    if drafts < 1 or improves < 0:
        raise VESValidationError("drafts must be >= 1 and improves must be >= 0")
    if not math.isfinite(timeout) or timeout <= 0:
        raise VESValidationError(
            f"timeout must be finite and > 0, got {timeout!r}"
        )
    if row_order not in ("input", "id"):
        raise VESValidationError(
            f"row_order must be 'input' or 'id', got {row_order!r}"
        )
    if not target_column or not target_column.strip():
        raise VESValidationError("target_column must be non-empty")
    if id_column is not None and not id_column.strip():
        raise VESValidationError("id_column must be non-empty when set")

    capability = _detect_backend()
    if not capability["available"]:
        raise VESBackendError(
            "VES regression backend unavailable: " + str(capability["error"])
        )

    public_dir_p = Path(public_dir)
    host_dir_p = Path(host_dir)
    file_hashes = _validate_inputs(
        public_dir_p, host_dir_p, assume_row_order=assume_row_order
    )

    workspace_p = Path(workspace) if workspace else Path.cwd() / "runs"
    workspace_p.mkdir(parents=True, exist_ok=True)
    output_p = Path(output) if output else workspace_p / MANIFEST_FILENAME

    search = importlib.import_module("ves_modeling.regression").run_regression_search
    try:
        result = search(
            public_dir_p,
            host_dir_p,
            drafts=drafts,
            improves=improves,
            workspace=workspace_p,
            generator=generator,
            dataset_name=dataset_name,
            fixture_dir=Path(fixture_dir) if fixture_dir else None,
            fallback_code=fallback_code,
            image=image,
            image_digest=image_digest,
            timeout_seconds=timeout,
            target_column=target_column,
            id_column=id_column,
            row_order=row_order,
            split_metadata=split_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - wrap unexpected backend errors
        raise RuntimeError(f"VES regression search failed: {exc}") from exc

    best_code_sha = (
        hashlib.sha256(result.best_code.encode("utf-8")).hexdigest()
        if result.best_code is not None
        else None
    )
    if result.status == "verified":
        if not result.best_code:
            raise RuntimeError(
                "status=verified but best_code is empty; refusing to "
                "report verified evidence"
            )
        required_artifacts = (
            result.run_dir / "summary.json",
            result.run_dir / "config.json",
            result.run_dir / "best_solution.py",
        )
        missing_artifacts = [
            str(path) for path in required_artifacts if not path.is_file()
        ]
        if missing_artifacts:
            raise RuntimeError(
                "status=verified but run_dir artifacts are missing: "
                + ", ".join(missing_artifacts)
            )
        disk_sha = _sha256(result.run_dir / "best_solution.py")
        if disk_sha != best_code_sha:
            raise RuntimeError(
                "status=verified but best_solution.py on disk does not match "
                f"best_code (disk sha256={disk_sha}, expected={best_code_sha})"
            )
    data_contract = getattr(result, "data_contract", None)
    if data_contract is None:
        snapshot = capability.get("capabilities_snapshot") or {}
        data_contract = snapshot.get("data_contract")

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "search",
        "backend": {
            "name": "ves_modeling.regression",
            "capability": {
                "available": capability["available"],
                "has_run_regression_search": capability[
                    "has_run_regression_search"
                ],
                "has_apply_regression_solution": capability[
                    "has_apply_regression_solution"
                ],
                "has_capabilities": capability["has_capabilities"],
                "result_fields_ok": capability["result_fields_ok"],
            },
            "api_schema_version": capability["api_schema_version"],
            "package_version": capability["package_version"],
        },
        "task": {
            "dataset_name": result.dataset_name,
            "generator": result.generator,
            "drafts": result.drafts,
            "improves": result.improves,
            "public_dir": str(public_dir_p),
            "host_dir": str(host_dir_p),
        },
        "result": {
            "status": result.status,
            "run_id": result.run_id,
            "rmse": result.best_rmse,
            "mae": result.best_mae,
            "rejected": result.rejected,
            "candidate_id": result.best_candidate_id,
        },
        "data_contract": data_contract,
        "artifacts": {
            "run_dir": str(result.run_dir),
            "summary": str(result.run_dir / "summary.json"),
            "config": str(result.run_dir / "config.json"),
            "best_solution": str(result.run_dir / "best_solution.py"),
        },
        "provenance": {
            "files_sha256": file_hashes,
            "best_code_sha256": best_code_sha,
            "generation_params": {
                "image": image,
                "image_digest": image_digest,
                "timeout_seconds": timeout,
                "fixture_dir": str(fixture_dir) if fixture_dir else None,
                "target_column": target_column,
                "id_column": id_column,
                "row_order": row_order,
                "split_metadata": split_metadata,
                "assume_row_order": assume_row_order,
            },
            "generated_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
    }
    _atomic_write_json(output_p, manifest)
    return manifest


def _validate_apply_inputs(public_dir: Path) -> dict[str, str]:
    """Fail-closed prechecks for apply mode (train + unknown test features)."""
    public_dir = public_dir.resolve()
    if not public_dir.is_dir():
        raise VESValidationError(f"public_dir is not a directory: {public_dir}")
    leaked = public_dir / "hidden_test_labels.csv"
    if leaked.is_file():
        raise VESValidationError(
            f"public_dir must not contain hidden_test_labels.csv (label leak): {leaked}"
        )
    required = ("train.csv", "test_features.csv")
    missing = [
        name for name in required if not (public_dir / name).is_file()
    ]
    if missing:
        raise VESValidationError(
            f"public_dir missing required files: {', '.join(missing)}"
        )

    train_path = public_dir / "train.csv"
    test_path = public_dir / "test_features.csv"
    train_cols = _csv_columns(train_path)
    test_cols = _csv_columns(test_path)
    if "target" not in train_cols:
        raise VESValidationError("train.csv must contain a 'target' column")
    if "target" in test_cols:
        raise VESValidationError(
            "test_features.csv must not contain a 'target' column"
        )
    expected_features = [col for col in train_cols if col != "target"]
    if test_cols != expected_features:
        raise VESValidationError(
            "feature columns mismatch between train.csv and test_features.csv; "
            f"expected exact order {expected_features}, got {test_cols}"
        )
    if _csv_row_count(train_path) < 1 or _csv_row_count(test_path) < 1:
        raise VESValidationError(
            "train.csv and test_features.csv must each contain at least one "
            "data row"
        )
    return {
        "public/train.csv": _sha256(train_path),
        "public/test_features.csv": _sha256(test_path),
    }


def apply_ves_regression(
    solution: str | os.PathLike[str],
    public_dir: str | os.PathLike[str],
    *,
    workspace: str | os.PathLike[str] | None = None,
    output: str | os.PathLike[str] | None = None,
    dataset_name: str = "regression",
    trusted_code: bool = False,
    image: str = "ves-modeling-runner:0.1",
    image_digest: str | None = None,
    timeout: float = 900.0,
    target_column: str = "target",
    id_column: str | None = None,
    row_order: str = "input",
) -> dict[str, Any]:
    """Apply a solution to unknown test features and write an apply manifest.

    Success status is always ``produced_unverified``: no official labels exist
    during apply, so no quality metric is produced and the result must never
    be cited as host-verified evidence.  Raises VESValidationError (1),
    VESBackendError (2) or RuntimeError (4) on failure; the CLI maps
    ``produced_unverified`` to exit code 5.
    """
    if sys.version_info < (3, 11):
        raise VESValidationError(
            f"Python >= 3.11 required, got {sys.version_info.major}."
            f"{sys.version_info.minor}"
        )
    if not math.isfinite(timeout) or timeout <= 0:
        raise VESValidationError(
            f"timeout must be finite and > 0, got {timeout!r}"
        )
    if row_order not in ("input", "id"):
        raise VESValidationError(
            f"row_order must be 'input' or 'id', got {row_order!r}"
        )
    if not target_column or not target_column.strip():
        raise VESValidationError("target_column must be non-empty")
    if id_column is not None and not id_column.strip():
        raise VESValidationError("id_column must be non-empty when set")

    capability = _detect_backend()
    if not capability["has_apply_regression_solution"]:
        raise VESBackendError(
            "VES apply backend unavailable: module has no "
            "apply_regression_solution"
        )

    solution_path = Path(solution)
    if solution_path.is_file():
        code = solution_path.read_text(encoding="utf-8")
        solution_ref = str(solution_path)
    else:
        code = str(solution)
        solution_ref = "<inline-code>"
    if not code.strip():
        raise VESValidationError("solution must be non-empty")

    public_dir_p = Path(public_dir)
    data_hashes = _validate_apply_inputs(public_dir_p)

    workspace_p = Path(workspace) if workspace else Path.cwd() / "runs"
    workspace_p.mkdir(parents=True, exist_ok=True)
    output_p = Path(output) if output else workspace_p / "ves_regression_apply_manifest.json"

    apply_fn = importlib.import_module(
        "ves_modeling.regression"
    ).apply_regression_solution
    try:
        result = apply_fn(
            code,
            public_dir_p,
            workspace=workspace_p,
            trusted_code=trusted_code,
            image=image,
            image_digest=image_digest,
            timeout_seconds=timeout,
            target_column=target_column,
            id_column=id_column,
            row_order=row_order,
        )
    except Exception as exc:  # noqa: BLE001 - wrap unexpected backend errors
        raise RuntimeError(f"VES regression apply failed: {exc}") from exc

    if result.status != "produced_unverified":
        raise RuntimeError(
            "apply must end with status=produced_unverified, "
            f"got {result.status!r}; refusing to treat it as a valid apply"
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply",
        "backend": {
            "name": "ves_modeling.regression",
            "capability": {
                "available": capability["available"],
                "has_run_regression_search": capability[
                    "has_run_regression_search"
                ],
                "has_apply_regression_solution": capability[
                    "has_apply_regression_solution"
                ],
                "has_capabilities": capability["has_capabilities"],
                "result_fields_ok": capability["result_fields_ok"],
            },
            "api_schema_version": capability["api_schema_version"],
            "package_version": capability["package_version"],
        },
        "task": {
            "dataset_name": dataset_name,
            "trusted_code": trusted_code,
            "public_dir": str(public_dir_p),
            "solution_ref": solution_ref,
        },
        "result": {
            "status": result.status,
            "run_id": result.run_id,
            "runner": getattr(result, "runner", None),
            "docker_image": getattr(result, "docker_image", None),
            "docker_digest": getattr(result, "docker_digest", None),
            "code_sha256": getattr(result, "code_sha256", None),
            "predictions_sha256": getattr(
                result, "predictions_sha256", None
            ),
        },
        "data_contract": getattr(result, "data_contract", None),
        "artifacts": {
            "run_dir": str(result.run_dir),
            "predictions": (
                str(result.predictions_path)
                if getattr(result, "predictions_path", None) is not None
                else None
            ),
            "summary": str(Path(result.run_dir) / "summary.json"),
            "stdout_log": str(getattr(result, "stdout_log", "")),
            "stderr_log": str(getattr(result, "stderr_log", "")),
        },
        "provenance": {
            "files_sha256": data_hashes,
            "generation_params": {
                "image": image,
                "image_digest": image_digest,
                "timeout_seconds": timeout,
                "trusted_code": trusted_code,
                "target_column": target_column,
                "id_column": id_column,
                "row_order": row_order,
            },
            "generated_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
    }
    _atomic_write_json(output_p, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a tabular regression subproblem through the VES host "
            "verifier and write a normalized Evidence manifest."
        )
    )
    parser.add_argument("--public-dir", help="candidate-visible dir (train.csv + test_features.csv)")
    parser.add_argument("--host-dir", help="host-only dir (hidden_test_labels.csv)")
    parser.add_argument("--workspace", help="VES run workspace (default: ./runs)")
    parser.add_argument("--output", help="normalized manifest output path (default: <workspace>/ves_regression_manifest.json)")
    parser.add_argument("--dataset-name", default="regression")
    parser.add_argument("--drafts", type=int, default=2)
    parser.add_argument("--improves", type=int, default=3)
    parser.add_argument("--generator", choices=("mock", "llm"), default="mock")
    parser.add_argument("--fixture-dir", help="mock fixtures directory")
    parser.add_argument("--fallback-code", help="path to fallback candidate code for generator=llm")
    parser.add_argument("--image", default="ves-modeling-runner:0.1", help="Docker image for generator=llm")
    parser.add_argument("--image-digest", help="Docker image digest (sha256:...) for generator=llm")
    parser.add_argument("--timeout", type=float, default=900.0, help="timeout seconds for generator=llm")
    parser.add_argument("--target-column", default="target", help="target column name (default: target)")
    parser.add_argument("--id-column", help="optional shared ID column for row_order=id")
    parser.add_argument("--row-order", choices=("input", "id"), default="input", help="row-order contract (default: input)")
    parser.add_argument("--split-metadata", help="JSON object of caller-supplied split provenance (optional)")
    parser.add_argument("--assume-row-order", action="store_true", help="explicitly accept row-order alignment without a shared ID column")
    parser.add_argument("--apply", action="store_true", help="apply mode: run apply_regression_solution on unknown test features")
    parser.add_argument("--solution", help="apply mode: path to best_solution.py (or inline code is not accepted via CLI)")
    parser.add_argument("--trusted-code", action="store_true", help="apply mode: allow local execution (trusted fixtures/tests only)")
    parser.add_argument("--check-only", action="store_true", help="only print backend capability and exit")
    args = parser.parse_args(argv)

    if args.check_only:
        capability = _detect_backend()
        print(json.dumps(capability, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if capability["available"] else 2
    if args.apply:
        if not args.public_dir or not args.solution:
            parser.error(
                "--apply requires --public-dir and --solution "
                "(unless --check-only)"
            )
    elif not args.public_dir or not args.host_dir:
        parser.error(
            "--public-dir and --host-dir are required for search mode "
            "(unless --check-only or --apply)"
        )

    fallback_code: str | None = None
    split_metadata: dict[str, Any] | None = None
    if args.split_metadata:
        try:
            parsed = json.loads(args.split_metadata)
        except json.JSONDecodeError as exc:
            print(
                "ves-regression validation error: "
                f"--split-metadata is not valid JSON: {exc}",
                file=sys.stderr,
            )
            return 1
        if not isinstance(parsed, dict):
            print(
                "ves-regression validation error: "
                "--split-metadata must be a JSON object",
                file=sys.stderr,
            )
            return 1
        split_metadata = parsed

    if args.fallback_code:
        try:
            fallback_code = Path(args.fallback_code).read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            print(
                "ves-regression validation error: "
                f"cannot read fallback code: {exc}",
                file=sys.stderr,
            )
            return 1

    apply_solution: str | None = None
    if args.apply:
        try:
            apply_solution = Path(args.solution).read_text(encoding="utf-8")
        except OSError as exc:
            print(
                "ves-regression validation error: "
                f"cannot read solution: {exc}",
                file=sys.stderr,
            )
            return 1

    try:
        if args.apply:
            manifest = apply_ves_regression(
                solution=apply_solution,
                public_dir=args.public_dir,
                workspace=args.workspace,
                output=args.output,
                dataset_name=args.dataset_name,
                trusted_code=args.trusted_code,
                image=args.image,
                image_digest=args.image_digest,
                timeout=args.timeout,
                target_column=args.target_column,
                id_column=args.id_column,
                row_order=args.row_order,
            )
        else:
            manifest = run_ves_regression(
            public_dir=args.public_dir,
            host_dir=args.host_dir,
            workspace=args.workspace,
            output=args.output,
            dataset_name=args.dataset_name,
            drafts=args.drafts,
            improves=args.improves,
            generator=args.generator,
            fixture_dir=args.fixture_dir,
            fallback_code=fallback_code,
            image=args.image,
            image_digest=args.image_digest,
            timeout=args.timeout,
            target_column=args.target_column,
            id_column=args.id_column,
            row_order=args.row_order,
            split_metadata=split_metadata,
            assume_row_order=args.assume_row_order,
            )
    except VESValidationError as exc:
        print(f"ves-regression validation error: {exc}", file=sys.stderr)
        return 1
    except VESBackendError as exc:
        print(f"ves-regression backend error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ves-regression runtime error: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    if manifest["operation"] == "apply":
        return 5
    return 0 if manifest["result"]["status"] == "verified" else 3


if __name__ == "__main__":
    raise SystemExit(main())
