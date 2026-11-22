from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_mapping import (
    load_bank_mapping,
    load_own_names,
    normalize_row,
)
from finance_copilot.ingestion.fx import FxRates

RowFactory = Callable[..., dict[str, str]]
CsvWriter = Callable[..., Path]
MAPPING = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")
OWN = frozenset({"demo freelancer"})


def test_payment_to_own_account_is_a_transfer_despite_spelling(
    wise_row: RowFactory, ecb_rates_csv: Path
) -> None:
    row = wise_row(**{"Target name": "  DEMO   Freelancer "})

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv), OWN)

    assert result is not None
    assert result["flow"] == "transfer"
    assert str(result["amount_eur"]) == "-50.00"


def test_incoming_payment_from_own_account_is_a_transfer(
    wise_row: RowFactory, ecb_rates_csv: Path
) -> None:
    row = wise_row(
        Direction="IN",
        **{"Source name": "Demo Freelancer", "Target name": "Demo Freelancer"},
    )

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv), OWN)

    assert result is not None
    assert result["flow"] == "transfer"


def test_payment_to_third_party_stays_an_expense(wise_row: RowFactory, ecb_rates_csv: Path) -> None:
    result = normalize_row(wise_row(), MAPPING, FxRates.from_ecb_csv(ecb_rates_csv), OWN)

    assert result is not None
    assert result["flow"] == "expense"


def test_conversion_is_not_reclassified(wise_row: RowFactory, ecb_rates_csv: Path) -> None:
    row = wise_row(Direction="NEUTRAL", **{"Target name": "Demo Freelancer"})

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv), OWN)

    assert result is not None
    assert result["flow"] == "conversion"


def test_own_names_are_normalized_when_loaded(tmp_path: Path) -> None:
    path = tmp_path / "own_accounts.yaml"
    path.write_text('names:\n  - "  Demo   FREELANCER "\n  - Second Name\n', encoding="utf-8")

    assert load_own_names(path) == frozenset({"demo freelancer", "second name"})


@pytest.mark.parametrize("content", [None, "", "names:\n"])
def test_missing_or_empty_own_accounts_file_means_no_names(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "own_accounts.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    assert load_own_names(path) == frozenset()


def test_ingest_applies_own_accounts_and_reports_flow_counts_only(
    tmp_path: Path,
    wise_row: RowFactory,
    write_wise_csv: CsvWriter,
    ecb_rates_csv: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings: Settings = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    settings.paths.fx_rates.parent.mkdir(parents=True)
    settings.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    settings.paths.own_accounts.parent.mkdir(parents=True)
    settings.paths.own_accounts.write_text("names: [My Own Name]\n", encoding="utf-8")
    source = write_wise_csv(
        [wise_row(), wise_row(ID="TRANSFER-2", **{"Target name": "My Own Name"})]
    )

    assert main(["ingest", "--bank", "wise", "--file", str(source)], settings) == 0

    output = capsys.readouterr().out
    assert "expense: 1" in output
    assert "transfer: 1" in output
    assert "My Own Name" not in output
    with duckdb.connect(str(settings.paths.warehouse), read_only=True) as connection:
        flows = connection.execute(
            "select transaction_id, flow from raw.bank_transactions order by 1"
        ).fetchall()
    assert flows == [("wise:TRANSFER-1", "expense"), ("wise:TRANSFER-2", "transfer")]
