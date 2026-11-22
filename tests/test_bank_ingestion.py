from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import duckdb

from finance_copilot.config import PROJECT_ROOT
from finance_copilot.ingestion.bank_csv import ingest_bank_csv
from finance_copilot.ingestion.bank_mapping import load_bank_mapping
from finance_copilot.ingestion.fx import FxRates

RowFactory = Callable[..., dict[str, str]]
CsvWriter = Callable[..., Path]
MAPPING = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")


def stored(warehouse: Path) -> list[tuple[str, Decimal]]:
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        rows = connection.execute(
            "select transaction_id, amount_eur from raw.bank_transactions order by 1"
        ).fetchall()
    return [(row[0], Decimal(row[1])) for row in rows]


def test_import_writes_rows_and_returns_count(
    tmp_path: Path, wise_row: RowFactory, write_wise_csv: CsvWriter, ecb_rates_csv: Path
) -> None:
    source = write_wise_csv([wise_row(), wise_row(ID="TRANSFER-2", Status="CANCELLED")])
    warehouse = tmp_path / "warehouse.duckdb"

    count = ingest_bank_csv(source, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv), warehouse)

    assert count == 1
    assert stored(warehouse) == [("wise:TRANSFER-1", Decimal("-50"))]


def test_repeated_import_creates_no_duplicates(
    tmp_path: Path, wise_row: RowFactory, write_wise_csv: CsvWriter, ecb_rates_csv: Path
) -> None:
    source = write_wise_csv([wise_row()])
    warehouse = tmp_path / "warehouse.duckdb"
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    ingest_bank_csv(source, MAPPING, rates, warehouse)
    ingest_bank_csv(source, MAPPING, rates, warehouse)

    assert len(stored(warehouse)) == 1


def test_overlapping_export_updates_existing_row_and_adds_new_one(
    tmp_path: Path, wise_row: RowFactory, write_wise_csv: CsvWriter, ecb_rates_csv: Path
) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    rates = FxRates.from_ecb_csv(ecb_rates_csv)
    first = write_wise_csv([wise_row()], "first.csv")
    second = write_wise_csv(
        [wise_row(**{"Target amount (after fees)": "60.00"}), wise_row(ID="TRANSFER-2")],
        "second.csv",
    )

    ingest_bank_csv(first, MAPPING, rates, warehouse)
    ingest_bank_csv(second, MAPPING, rates, warehouse)

    assert stored(warehouse) == [
        ("wise:TRANSFER-1", Decimal("-60")),
        ("wise:TRANSFER-2", Decimal("-50")),
    ]
