from pathlib import Path

import dagster as dg
import duckdb
import pytest

from finance_copilot.cli import app_command, orchestrator_command
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.orchestration.pipeline import (
    build_definitions,
    data_target,
    matching_import_files,
    run_imports,
    run_pipeline,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )


def test_target_defaults_to_demo() -> None:
    assert data_target({}) == "demo"
    assert data_target({"FINANCE_COPILOT_DATA": "private"}) == "private"
    with pytest.raises(ValueError):
        data_target({"FINANCE_COPILOT_DATA": "production"})


def test_import_files_match_exports_but_not_helper_tables(settings: Settings) -> None:
    private = settings.paths.private_data
    private.mkdir(parents=True)
    for name in (
        "wise-transactions-2026.csv",
        "wise-transactions-2025.csv",
        "raiffeisen-2026.csv",
        "raiffeisen-empfaenger.csv",
        "trade-republic-2026.csv",
        "trade-republic-empfaenger.csv",
    ):
        (private / name).write_text("x", encoding="utf-8")

    found = [(bank, path.name) for bank, path in matching_import_files(settings)]

    assert found == [
        ("wise", "wise-transactions-2025.csv"),
        ("wise", "wise-transactions-2026.csv"),
        ("raiffeisen", "raiffeisen-2026.csv"),
        ("trade_republic", "trade-republic-2026.csv"),
    ]


def test_private_import_without_files_fails(settings: Settings) -> None:
    settings.paths.private_data.mkdir(parents=True)

    with pytest.raises(dg.Failure):
        run_imports(settings, "private")


def test_definitions_connect_import_to_dbt_marts(settings: Settings) -> None:
    definitions = build_definitions("demo", settings)

    graph = definitions.resolve_asset_graph()
    source = dg.AssetKey(["raw", "bank_transactions"])
    staging = next(key for key in graph.get_all_asset_keys() if key.path[-1].startswith("stg_bank"))
    marts = {key.path[-1] for key in graph.get_all_asset_keys()}

    assert source in graph.get(staging).parent_keys
    assert {"fct_transactions", "mart_monthly_pnl", "mart_tax_reserve"} <= marts


def test_demo_pipeline_builds_marts_and_leaves_private_data_alone(settings: Settings) -> None:
    assert run_pipeline("demo", settings) is True

    demo = settings.paths.demo_data / "warehouse.duckdb"
    with duckdb.connect(str(demo), read_only=True) as connection:
        months = connection.execute("select count(*) from marts.mart_monthly_pnl").fetchone()
    assert months == (12,)
    assert not settings.paths.warehouse.exists()


def test_dashboard_is_local_and_without_telemetry() -> None:
    command = app_command()

    assert "--server.address=127.0.0.1" in command
    assert "--browser.gatherUsageStats=false" in command
    assert "--client.toolbarMode=minimal" in command


def test_orchestrator_is_local() -> None:
    command = orchestrator_command()

    assert command[command.index("--host") + 1] == "127.0.0.1"
