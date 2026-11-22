"""Load normalized bank transactions into DuckDB with dlt (FR-02)."""

import csv
import os
from pathlib import Path

import dlt

from finance_copilot.ingestion.bank_mapping import BankMapping, normalize_row
from finance_copilot.ingestion.fx import FxRates


def read_bank_csv(
    path: Path,
    mapping: BankMapping,
    rates: FxRates,
    own_names: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = (normalize_row(row, mapping, rates, own_names) for row in csv.DictReader(file))
        return [row for row in rows if row is not None]


def ingest_bank_csv(path: Path, mapping: BankMapping, rates: FxRates, warehouse: Path) -> int:
    """Upsert one export by transaction id and return the number of accepted rows."""
    return load_bank_rows(read_bank_csv(path, mapping, rates), warehouse)


def load_bank_rows(rows: list[dict[str, object]], warehouse: Path) -> int:
    """Upsert normalized rows by transaction id."""
    if not rows:
        return 0

    # RB-04: financial tooling must not send usage data anywhere.
    os.environ["RUNTIME__DLTHUB_TELEMETRY"] = "false"
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    resource = dlt.resource(
        rows,
        name="bank_transactions",
        primary_key="transaction_id",
        write_disposition="merge",
    )
    pipeline = dlt.pipeline(
        pipeline_name="finance_copilot_bank",
        pipelines_dir=str(warehouse.parent / ".dlt"),
        destination=dlt.destinations.duckdb(str(warehouse)),
        dataset_name="raw",
    )
    pipeline.run(resource)
    return len(rows)
