"""Dagster assets for bank imports and dbt models (NFR-07)."""

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, DataTarget, Settings, data_target

__all__ = [
    "build_definitions",
    "data_target",
    "matching_import_files",
    "run_imports",
    "run_pipeline",
]

DBT_DIR = PROJECT_ROOT / "dbt"
SOURCE_KEYS = tuple(
    dg.AssetKey(["raw", table]) for table in ("bank_transactions", "categories", "reserve_settings")
)


def matching_import_files(settings: Settings) -> list[tuple[str, Path]]:
    """List private exports in the configured bank order."""
    return [
        (source.bank, path)
        for source in settings.imports
        for path in sorted(settings.paths.private_data.glob(source.pattern))
    ]


def run_imports(settings: Settings, target: DataTarget) -> int:
    """Load all exports and return the number of files. Only counts are logged."""
    if target == "demo":
        if main(["demo"], settings) != 0:
            raise dg.Failure("Demo import failed.")
        return 1
    files = matching_import_files(settings)
    if not files:
        raise dg.Failure("No bank exports found in the private data folder.")
    for bank, path in files:
        if main(["ingest", "--bank", bank, "--file", str(path)], settings) != 0:
            raise dg.Failure(f"Import failed for {bank}.")
    return len(files)


def _runtime_env(settings: Settings) -> dict[str, str]:
    return {
        "FINANCE_COPILOT_DEMO_WAREHOUSE": str(settings.paths.demo_data / "warehouse.duckdb"),
        "FINANCE_COPILOT_WAREHOUSE": str(settings.paths.warehouse),
        "DAGSTER_DISABLE_TELEMETRY": "yes",
    }


@contextmanager
def _temporary_env(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _prepare_project(target: DataTarget, settings: Settings) -> DbtProject:
    target_path = Path("target") / target
    executable = shutil.which("dbt", path=str(Path(sys.executable).parent)) or "dbt"
    subprocess.run(  # noqa: S603
        [
            executable,
            "parse",
            "--project-dir",
            str(DBT_DIR),
            "--profiles-dir",
            str(DBT_DIR),
            "--target",
            target,
            "--target-path",
            str(target_path),
        ],
        check=True,
        capture_output=True,
        env=os.environ | _runtime_env(settings),
    )
    return DbtProject(
        project_dir=DBT_DIR, profiles_dir=DBT_DIR, target=target, target_path=target_path
    )


def _build_assets(
    target: DataTarget, settings: Settings
) -> tuple[Sequence[dg.AssetsDefinition], dict[str, Any]]:
    project = _prepare_project(target, settings)
    environment = _runtime_env(settings)

    @dg.multi_asset(
        name="bank_imports",
        specs=[
            dg.AssetSpec(key, group_name="ingestion", kinds={"dlt", "duckdb"})
            for key in SOURCE_KEYS
        ],
    )
    def bank_imports() -> Iterator[dg.MaterializeResult[Any]]:
        """Import bank exports, categories and pot settings into the warehouse."""
        files = run_imports(settings, target)
        for key in SOURCE_KEYS:
            yield dg.MaterializeResult(asset_key=key, metadata={"files": files})

    @dbt_assets(manifest=project.manifest_path, name="finance_copilot_dbt")
    def dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
        with _temporary_env(environment):
            yield from dbt.cli(["build"], context=context).stream()

    return [bank_imports, dbt_models], {"dbt": DbtCliResource(project_dir=project)}


def build_definitions(target: DataTarget, settings: Settings) -> dg.Definitions:
    assets, resources = _build_assets(target, settings)
    return dg.Definitions(assets=assets, resources=resources)


def run_pipeline(target: DataTarget, settings: Settings) -> bool:
    """Run imports and all dbt models once in this process."""
    with _temporary_env({"DAGSTER_DISABLE_TELEMETRY": "yes"}):
        assets, resources = _build_assets(target, settings)
        result = dg.materialize(assets, resources=resources, raise_on_error=False)
    return bool(result.success)
