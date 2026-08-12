#!/usr/bin/env python3
"""Generic multi-slice adapter between the ves-mathmodel-skill workflow and VES.

Only public ``ves_modeling.<slice>`` symbols are consumed:
``run_<slice>_search``, ``apply_<slice>_solution``, ``capabilities()``,
``API_SCHEMA_VERSION`` and the public result dataclass (via ``to_summary()``).
VES internal implementations are never imported.  The adapter performs
fail-closed prechecks (path isolation, host-label leaks, host files present),
normalizes every slice into one Evidence manifest schema, and never treats
``status != "verified"`` as success evidence.

Exit codes:
    0  search completed and status == "verified"
    1  input/precheck error
    2  backend unavailable or capability/signature mismatch
    3  search completed but status != "verified" (manifest still written)
    4  unexpected backend exception
    5  apply completed with status == "produced_unverified" (never evidence)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.1"
SEARCH_MANIFEST = "ves_problem_manifest.json"
APPLY_MANIFEST = "ves_problem_apply_manifest.json"

# slice -> (needs_host, required public files, host files, default extra kwargs)
# required_public=[] means: defer to VES data-contract validation.
SLICE_CATALOG: dict[str, dict[str, Any]] = {
    "regression": {
        "needs_host": True,
        "required_public": ("train.csv", "test_features.csv"),
        "host_files": ("hidden_test_labels.csv",),
        "defaults": {"target_column": "target", "id_column": None, "row_order": "input"},
    },
    "forecasting": {
        "needs_host": True,
        "required_public": ("train.csv", "test_features.csv"),
        "host_files": ("hidden_test_labels.csv",),
        "defaults": {
            "time_column": "timestamp",
            "series_id_column": "series_id",
            "target_column": "target",
            "frequency": "D",
            "row_order": "key",
        },
    },
    "classification": {
        "needs_host": True,
        "required_public": ("train.csv", "test_features.csv"),
        "host_files": ("hidden_test_labels.csv",),
        "defaults": {"label_column": "target", "id_column": None, "row_order": "input"},
    },
    "ode": {
        "needs_host": True,
        "required_public": ("train.csv", "test_features.csv"),
        "host_files": ("hidden_test_values.csv",),
        "defaults": {},
    },
    "clustering": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_labels.csv",),
        "defaults": {},
    },
    "anomaly": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_labels.csv",),
        "defaults": {},
    },
    "recommendation": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_ratings.csv",),
        "defaults": {},
    },
    "probabilistic": {
        "needs_host": True,
        "required_public": ("problem.json",),
        "host_files": ("hidden_parameters.json",),
        "defaults": {},
    },
    "association": {
        "needs_host": True,
        "required_public": ("train.csv",),
        "host_files": ("hidden_test_transactions.csv",),
        "defaults": {},
    },
    "survival": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_outcomes.csv",),
        "defaults": {},
    },
    "markov": {
        "needs_host": True,
        "required_public": ("problem.json",),
        "host_files": ("hidden_parameters.json",),
        "defaults": {},
    },
    "changepoint": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_changepoints.csv",),
        "defaults": {},
    },
    "seqpattern": {
        "needs_host": True,
        "required_public": (),
        "host_files": ("hidden_test_sequences.csv",),
        "defaults": {},
    },
    "optimization": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {"tolerance": 1e-6},
    },
    "graph": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "montecarlo": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "multiobjective": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "queueing": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "assignment": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "binpacking": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "lqr": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "sir": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "cellular": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "networksir": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
    "game": {
        "needs_host": False,
        "required_public": ("problem.json",),
        "host_files": (),
        "defaults": {},
    },
}

COMMON_SEARCH_PARAMS = (
    "drafts",
    "improves",
    "workspace",
    "generator",
    "dataset_name",
    "fixture_dir",
    "fallback_code",
    "image",
    "image_digest",
    "timeout_seconds",
    "split_metadata",
)
HOST_LABEL_FILENAMES = (
    "hidden_test_labels.csv",
    "hidden_test_values.csv",
    "hidden_test_ratings.csv",
    "hidden_parameters.json",
    "hidden_test_transactions.csv",
    "hidden_test_outcomes.csv",
    "hidden_test_changepoints.csv",
    "hidden_test_sequences.csv",
)


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


def _file_hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {name: _sha256(path) for name, path in paths.items()}


def _detect_slice(slice_name: str) -> dict[str, Any]:
    """Stable-symbol capability detection for one slice."""
    capability: dict[str, Any] = {
        "available": False,
        "module": f"ves_modeling.{slice_name}",
        "slice": slice_name,
        "error": None,
        "has_search": False,
        "search_signature_ok": False,
        "missing_search_params": [],
        "has_apply": False,
        "apply_signature_ok": False,
        "has_capabilities": False,
        "api_schema_version": None,
        "verified_metrics": [],
        "package_version": None,
    }
    try:
        module = importlib.import_module(f"ves_modeling.{slice_name}")
    except Exception as exc:  # noqa: BLE001 - report any import failure clearly
        capability["error"] = f"cannot import ves_modeling.{slice_name}: {exc}"
        return capability
    try:
        capability["package_version"] = importlib.metadata.version("ves-modeling")
    except Exception:  # noqa: BLE001 - metadata absence is not fatal
        capability["package_version"] = None

    search = getattr(module, f"run_{slice_name}_search", None)
    capability["has_search"] = search is not None
    if search is not None:
        try:
            params = set(inspect.signature(search).parameters)
        except (TypeError, ValueError):
            params = set()
        missing = [
            name for name in ("public_dir", "drafts", "improves", "workspace", "generator")
            if name not in params
        ]
        capability["missing_search_params"] = missing
        capability["search_signature_ok"] = not missing

    apply_fn = getattr(module, f"apply_{slice_name}_solution", None)
    capability["has_apply"] = apply_fn is not None
    if apply_fn is not None:
        try:
            signature = inspect.signature(apply_fn)
            params = set(signature.parameters)
        except (TypeError, ValueError):
            signature = None
            params = set()
        required_apply = {
            "solution",
            "public_dir",
            "workspace",
            "trusted_code",
            "image",
            "image_digest",
            "timeout_seconds",
        }
        has_var_keyword = bool(
            signature
            and any(
                item.kind == inspect.Parameter.VAR_KEYWORD
                for item in signature.parameters.values()
            )
        )
        capability["apply_signature_ok"] = (
            required_apply <= params or has_var_keyword
        )

    caps = getattr(module, "capabilities", None)
    capability["has_capabilities"] = callable(caps)
    capability["api_schema_version"] = getattr(module, "API_SCHEMA_VERSION", None)
    try:
        snapshot = caps() if callable(caps) else None
        if isinstance(snapshot, dict):
            capability["capabilities_snapshot"] = snapshot
            capability["verified_metrics"] = list(
                snapshot.get("verified_metrics", [])
            )
    except Exception:  # noqa: BLE001 - probing must never crash the check
        capability["capabilities_snapshot"] = None

    capability["available"] = (
        capability["has_search"]
        and capability["search_signature_ok"]
    )
    if not capability["available"]:
        capability["error"] = (
            f"slice {slice_name}: search missing or signature mismatch"
        )
    return capability


def _validate_inputs(
    slice_name: str,
    public_dir: Path,
    host_dir: Path | None,
) -> dict[str, str]:
    """Fail-closed prechecks. Returns {relative_path: sha256}."""
    meta = SLICE_CATALOG[slice_name]
    public_dir = public_dir.resolve()
    host_dir = host_dir.resolve() if host_dir is not None else None
    if not public_dir.is_dir():
        raise VESValidationError(f"public_dir is not a directory: {public_dir}")
    if host_dir is not None:
        if (
            host_dir == public_dir
            or public_dir in host_dir.parents
            or host_dir in public_dir.parents
        ):
            raise VESValidationError(
                "host_dir and public_dir must be disjoint directories "
                "(host leak)"
            )
        if not host_dir.is_dir():
            raise VESValidationError(f"host_dir is not a directory: {host_dir}")

    for name in HOST_LABEL_FILENAMES:
        if (public_dir / name).is_file():
            raise VESValidationError(
                f"public_dir must not contain {name} (label leak)"
            )

    missing_public = [
        name for name in meta["required_public"] if not (public_dir / name).is_file()
    ]
    if missing_public:
        raise VESValidationError(
            f"public_dir missing required files: {', '.join(missing_public)}"
        )

    hashes: dict[str, str] = {}
    for name in meta["required_public"]:
        hashes[f"public/{name}"] = _sha256(public_dir / name)

    if meta["needs_host"]:
        if host_dir is None:
            raise VESValidationError(
                f"slice {slice_name} requires --host-dir"
            )
        missing_host = [
            name for name in meta["host_files"] if not (host_dir / name).is_file()
        ]
        if missing_host:
            raise VESValidationError(
                f"host_dir missing required files: {', '.join(missing_host)}"
            )
        for name in meta["host_files"]:
            hashes[f"host/{name}"] = _sha256(host_dir / name)
    return hashes


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


def _result_summary(result: Any) -> dict[str, Any]:
    to_summary = getattr(result, "to_summary", None)
    if callable(to_summary):
        try:
            value = to_summary()
            if isinstance(value, dict):
                return value
        except Exception:  # noqa: BLE001 - fall back to attribute reads
            pass
    return {}


def _metric_values(result: Any, summary: dict[str, Any], metrics: list[str]) -> dict:
    values: dict[str, Any] = {}
    for metric in metrics:
        value = summary.get(f"best_{metric}")
        if value is None:
            value = getattr(result, f"best_{metric}", None)
        if value is None:
            value = getattr(result, f"best_{metric}_matrix", None)
        values[metric] = value
    return values


def run_ves_problem(
    slice_name: str,
    public_dir: str | os.PathLike[str],
    host_dir: str | os.PathLike[str] | None = None,
    *,
    workspace: str | os.PathLike[str] | None = None,
    output: str | os.PathLike[str] | None = None,
    dataset_name: str | None = None,
    drafts: int = 2,
    improves: int = 3,
    generator: str = "mock",
    fixture_dir: str | os.PathLike[str] | None = None,
    fallback_code: str | None = None,
    image: str = "ves-modeling-runner:0.1",
    image_digest: str | None = None,
    timeout: float = 900.0,
    split_metadata: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a VES slice search and return the normalized manifest dict."""
    if slice_name not in SLICE_CATALOG:
        raise VESValidationError(
            f"unknown slice {slice_name!r}; choose from {sorted(SLICE_CATALOG)}"
        )
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
        raise VESValidationError(f"timeout must be finite and > 0, got {timeout!r}")

    capability = _detect_slice(slice_name)
    if not capability["available"]:
        raise VESBackendError(
            "VES backend unavailable: " + str(capability["error"])
        )

    meta = SLICE_CATALOG[slice_name]
    public_dir_p = Path(public_dir)
    host_dir_p = Path(host_dir) if host_dir is not None else None
    file_hashes = _validate_inputs(slice_name, public_dir_p, host_dir_p)

    workspace_p = Path(workspace) if workspace else Path.cwd() / "runs"
    workspace_p.mkdir(parents=True, exist_ok=True)
    output_p = Path(output) if output else workspace_p / SEARCH_MANIFEST

    module = importlib.import_module(f"ves_modeling.{slice_name}")
    search = getattr(module, f"run_{slice_name}_search")
    params = set(inspect.signature(search).parameters)
    kwargs: dict[str, Any] = {
        "drafts": drafts,
        "improves": improves,
        "workspace": workspace_p,
        "generator": generator,
        "dataset_name": dataset_name or slice_name,
        "fixture_dir": Path(fixture_dir) if fixture_dir else None,
        "fallback_code": fallback_code,
        "image": image,
        "image_digest": image_digest,
        "timeout_seconds": timeout,
        "split_metadata": split_metadata,
    }
    kwargs = {k: v for k, v in kwargs.items() if k in params}
    for key, value in {**meta["defaults"], **(extra or {})}.items():
        if key in params:
            kwargs[key] = value
    if "host_dir" in params:
        kwargs["host_dir"] = host_dir_p
    try:
        result = search(public_dir_p, **kwargs)
    except Exception as exc:  # noqa: BLE001 - wrap unexpected backend errors
        raise RuntimeError(f"VES {slice_name} search failed: {exc}") from exc

    summary = _result_summary(result)
    metrics = _metric_values(
        result, summary, capability.get("verified_metrics") or []
    )
    data_contract = getattr(result, "data_contract", None) or summary.get(
        "data_contract"
    )
    best_code = getattr(result, "best_code", None)
    best_code_sha = (
        hashlib.sha256(best_code.encode("utf-8")).hexdigest()
        if best_code is not None
        else None
    )
    run_dir = Path(getattr(result, "run_dir"))
    if getattr(result, "status", None) == "verified":
        if not best_code:
            raise RuntimeError(
                "status=verified but best_code is empty; refusing to report evidence"
            )
        required_artifacts = (
            run_dir / "summary.json",
            run_dir / "best_solution.py",
        )
        missing_artifacts = [
            str(path) for path in required_artifacts if not path.is_file()
        ]
        if missing_artifacts:
            raise RuntimeError(
                "status=verified but run_dir artifacts are missing: "
                + ", ".join(missing_artifacts)
            )
        disk_sha = _sha256(run_dir / "best_solution.py")
        if disk_sha != best_code_sha:
            raise RuntimeError(
                "status=verified but best_solution.py on disk does not match "
                f"best_code (disk sha256={disk_sha}, expected={best_code_sha})"
            )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "search",
        "slice": slice_name,
        "backend": {
            "name": f"ves_modeling.{slice_name}",
            "capability": {
                "available": capability["available"],
                "has_search": capability["has_search"],
                "has_apply": capability["has_apply"],
                "has_capabilities": capability["has_capabilities"],
            },
            "api_schema_version": capability["api_schema_version"],
            "package_version": capability["package_version"],
            "verified_metrics": capability["verified_metrics"],
        },
        "task": {
            "slice": slice_name,
            "dataset_name": getattr(result, "dataset_name", dataset_name or slice_name),
            "generator": getattr(result, "generator", generator),
            "drafts": getattr(result, "drafts", drafts),
            "improves": getattr(result, "improves", improves),
            "public_dir": str(public_dir_p),
            "host_dir": str(host_dir_p) if host_dir_p is not None else None,
        },
        "result": {
            "status": getattr(result, "status", "unknown"),
            "run_id": getattr(result, "run_id", None),
            "metrics": metrics,
            "rejected": getattr(result, "rejected", None),
            "candidate_id": getattr(result, "best_candidate_id", None),
        },
        "data_contract": data_contract,
        "artifacts": {
            "run_dir": str(run_dir),
            "summary": str(run_dir / "summary.json"),
            "best_solution": str(run_dir / "best_solution.py"),
        },
        "provenance": {
            "files_sha256": file_hashes,
            "best_code_sha256": best_code_sha,
            "generation_params": {
                "image": image,
                "image_digest": image_digest,
                "timeout_seconds": timeout,
                "fixture_dir": str(fixture_dir) if fixture_dir else None,
                "slice_defaults": meta["defaults"],
                "extra": extra or {},
            },
            "generated_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
    }
    _atomic_write_json(output_p, manifest)
    return manifest


def apply_ves_problem(
    slice_name: str,
    solution: str | os.PathLike[str],
    public_dir: str | os.PathLike[str],
    *,
    workspace: str | os.PathLike[str] | None = None,
    output: str | os.PathLike[str] | None = None,
    dataset_name: str | None = None,
    trusted_code: bool = False,
    image: str = "ves-modeling-runner:0.1",
    image_digest: str | None = None,
    timeout: float = 900.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a slice solution to unknown inputs; always produced_unverified."""
    if slice_name not in SLICE_CATALOG:
        raise VESValidationError(
            f"unknown slice {slice_name!r}; choose from {sorted(SLICE_CATALOG)}"
        )
    capability = _detect_slice(slice_name)
    if not capability["has_apply"]:
        raise VESBackendError(
            f"VES apply unavailable for slice {slice_name}: no apply fn"
        )
    if not math.isfinite(timeout) or timeout <= 0:
        raise VESValidationError(f"timeout must be finite and > 0, got {timeout!r}")

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
    meta = SLICE_CATALOG[slice_name]
    file_hashes: dict[str, str] = {}
    if not public_dir_p.is_dir():
        raise VESValidationError(f"public_dir is not a directory: {public_dir_p}")
    for name in HOST_LABEL_FILENAMES:
        if (public_dir_p / name).is_file():
            raise VESValidationError(
                f"public_dir must not contain {name} (label leak)"
            )
    missing_public = [
        name for name in meta["required_public"] if not (public_dir_p / name).is_file()
    ]
    if missing_public:
        raise VESValidationError(
            f"public_dir missing required files: {', '.join(missing_public)}"
        )
    for name in meta["required_public"]:
        file_hashes[f"public/{name}"] = _sha256(public_dir_p / name)

    workspace_p = Path(workspace) if workspace else Path.cwd() / "runs"
    workspace_p.mkdir(parents=True, exist_ok=True)
    output_p = Path(output) if output else workspace_p / APPLY_MANIFEST

    module = importlib.import_module(f"ves_modeling.{slice_name}")
    apply_fn = getattr(module, f"apply_{slice_name}_solution")
    signature = inspect.signature(apply_fn)
    params = set(signature.parameters)
    has_var_keyword = any(
        item.kind == inspect.Parameter.VAR_KEYWORD
        for item in signature.parameters.values()
    )
    kwargs: dict[str, Any] = {
        "workspace": workspace_p,
        "trusted_code": trusted_code,
        "image": image,
        "image_digest": image_digest,
        "timeout_seconds": timeout,
    }
    kwargs = (
        kwargs
        if has_var_keyword
        else {k: v for k, v in kwargs.items() if k in params}
    )
    for key, value in (extra or {}).items():
        if key in params:
            kwargs[key] = value
    try:
        result = apply_fn(code, public_dir_p, **kwargs)
    except Exception as exc:  # noqa: BLE001 - wrap unexpected backend errors
        raise RuntimeError(f"VES {slice_name} apply failed: {exc}") from exc

    if getattr(result, "status", None) != "produced_unverified":
        raise RuntimeError(
            f"apply for {slice_name} must end with produced_unverified, "
            f"got {getattr(result, 'status', None)!r}"
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply",
        "slice": slice_name,
        "backend": {
            "name": f"ves_modeling.{slice_name}",
            "capability": {
                "available": capability["available"],
                "has_search": capability["has_search"],
                "has_apply": capability["has_apply"],
                "has_capabilities": capability["has_capabilities"],
            },
            "api_schema_version": capability["api_schema_version"],
            "package_version": capability["package_version"],
        },
        "task": {
            "slice": slice_name,
            "dataset_name": dataset_name or slice_name,
            "trusted_code": trusted_code,
            "public_dir": str(public_dir_p),
            "solution_ref": solution_ref,
        },
        "result": {
            "status": getattr(result, "status", None),
            "run_id": getattr(result, "run_id", None),
            "runner": getattr(result, "runner", None),
            "docker_image": getattr(result, "docker_image", None),
            "docker_digest": getattr(result, "docker_digest", None),
            "code_sha256": getattr(result, "code_sha256", None),
            "predictions_sha256": getattr(result, "predictions_sha256", None),
        },
        "data_contract": getattr(result, "data_contract", None),
        "artifacts": {
            "run_dir": str(getattr(result, "run_dir", "")),
            "predictions": (
                str(result.predictions_path)
                if getattr(result, "predictions_path", None) is not None
                else None
            ),
            "summary": str(
                Path(getattr(result, "run_dir")) / "summary.json"
            ),
        },
        "provenance": {
            "files_sha256": file_hashes,
            "generation_params": {
                "image": image,
                "image_digest": image_digest,
                "timeout_seconds": timeout,
                "trusted_code": trusted_code,
                "extra": extra or {},
            },
            "generated_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
    }
    _atomic_write_json(output_p, manifest)
    return manifest


def _parse_set(values: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise VESValidationError(f"--set expects key=value, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw.split(",") if "," in raw else raw
        parsed[key] = value
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run any VES vertical slice and write a normalized Evidence manifest."
    )
    parser.add_argument("--slice", help="VES slice name (e.g. regression, forecasting, optimization)")
    parser.add_argument("--public-dir", help="candidate-visible dir")
    parser.add_argument("--host-dir", help="host-only dir (required for label slices)")
    parser.add_argument("--workspace", help="VES run workspace (default: ./runs)")
    parser.add_argument("--output", help="manifest output path")
    parser.add_argument("--dataset-name")
    parser.add_argument("--drafts", type=int, default=2)
    parser.add_argument("--improves", type=int, default=3)
    parser.add_argument("--generator", choices=("mock", "llm"), default="mock")
    parser.add_argument("--fixture-dir")
    parser.add_argument("--fallback-code")
    parser.add_argument("--image", default="ves-modeling-runner:0.1")
    parser.add_argument("--image-digest")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="slice-specific kwarg (repeatable; JSON or comma list)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--solution")
    parser.add_argument("--trusted-code", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--list-slices", action="store_true")
    args = parser.parse_args(argv)

    if args.list_slices:
        for name in sorted(SLICE_CATALOG):
            needs = "host" if SLICE_CATALOG[name]["needs_host"] else "no-host"
            print(f"{name:16s} {needs}")
        return 0
    if args.check_only:
        if not args.slice:
            print("--slice is required with --check-only")
            return 2
        capability = _detect_slice(args.slice)
        print(json.dumps(capability, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if capability["available"] else 2
    if not args.slice or not args.public_dir:
        parser.error("--slice and --public-dir are required (unless --list-slices)")

    try:
        extra = _parse_set(args.set)
    except VESValidationError as exc:
        print(f"ves-problem validation error: {exc}", file=sys.stderr)
        return 1

    fallback_code: str | None = None
    if args.fallback_code:
        try:
            fallback_code = Path(args.fallback_code).read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"ves-problem validation error: cannot read fallback code: {exc}",
                file=sys.stderr,
            )
            return 1

    solution: str | None = None
    if args.apply:
        try:
            solution = Path(args.solution).read_text(encoding="utf-8")
        except (OSError, TypeError) as exc:
            print(
                f"ves-problem validation error: cannot read solution: {exc}",
                file=sys.stderr,
            )
            return 1

    try:
        if args.apply:
            manifest = apply_ves_problem(
                args.slice,
                solution,
                args.public_dir,
                workspace=args.workspace,
                output=args.output,
                dataset_name=args.dataset_name,
                trusted_code=args.trusted_code,
                image=args.image,
                image_digest=args.image_digest,
                timeout=args.timeout,
                extra=extra,
            )
        else:
            manifest = run_ves_problem(
                args.slice,
                args.public_dir,
                args.host_dir,
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
                extra=extra,
            )
    except VESValidationError as exc:
        print(f"ves-problem validation error: {exc}", file=sys.stderr)
        return 1
    except VESBackendError as exc:
        print(f"ves-problem backend error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ves-problem runtime error: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    if manifest["operation"] == "apply":
        return 5
    return 0 if manifest["result"]["status"] == "verified" else 3


if __name__ == "__main__":
    raise SystemExit(main())
