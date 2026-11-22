from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings

RowFactory = Callable[..., dict[str, str]]
CsvWriter = Callable[..., Path]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )


def row_count(warehouse: Path) -> int:
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        result = connection.execute("select count(*) from raw.bank_transactions").fetchone()
    assert result is not None
    return int(result[0])


def test_demo_loads_a_separate_warehouse(settings: Settings) -> None:
    assert main(["demo"], settings) == 0

    assert row_count(settings.paths.demo_data / "warehouse.duckdb") > 0
    assert not settings.paths.warehouse.exists()


def test_ingest_reports_count_without_financial_content(
    settings: Settings,
    wise_row: RowFactory,
    write_wise_csv: CsvWriter,
    ecb_rates_csv: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings.paths.fx_rates.parent.mkdir(parents=True)
    settings.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    source = write_wise_csv([wise_row()])

    assert main(["ingest", "--bank", "wise", "--file", str(source)], settings) == 0

    output = capsys.readouterr().out
    assert "1" in output
    assert "Hosting GmbH" not in output
    assert "Server March" not in output
    assert row_count(settings.paths.warehouse) == 1


def test_ingest_without_rates_fails_with_hint(
    settings: Settings,
    wise_row: RowFactory,
    write_wise_csv: CsvWriter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_wise_csv([wise_row()])

    assert main(["ingest", "--bank", "wise", "--file", str(source)], settings) == 1

    assert "fetch-fx" in capsys.readouterr().err
    assert not settings.paths.warehouse.exists()


def test_ingest_malformed_row_fails_without_content(
    settings: Settings,
    wise_row: RowFactory,
    write_wise_csv: CsvWriter,
    ecb_rates_csv: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings.paths.fx_rates.parent.mkdir(parents=True)
    settings.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    source = write_wise_csv([wise_row(Direction="SIDEWAYS", Reference="SECRET-REFERENCE")])

    assert main(["ingest", "--bank", "wise", "--file", str(source)], settings) == 1

    captured = capsys.readouterr()
    assert "TRANSFER-1" in captured.err
    assert "SECRET-REFERENCE" not in captured.out + captured.err
    assert not settings.paths.warehouse.exists()


def test_ingest_unknown_bank_fails(settings: Settings, tmp_path: Path) -> None:
    assert main(["ingest", "--bank", "nope", "--file", str(tmp_path / "x.csv")], settings) == 1
