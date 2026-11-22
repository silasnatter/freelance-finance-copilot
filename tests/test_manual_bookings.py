from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_csv import load_bank_rows
from finance_copilot.ingestion.manual import (
    load_manual_bookings,
    manual_rows,
    sync_manual_bookings,
)


def write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


BASIC = """
bookings:
  - {date: 2026-02-28, payee: SVS, amount: 900.50, type: expense, note: Q1}
  - {date: 2026-05-15, payee: Finanzamt, amount: "1.200,00", type: tax}
"""


def stored(warehouse: Path) -> list[tuple[str, str, Decimal]]:
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        rows = connection.execute(
            "select bank, flow, business_amount_eur from raw.bank_transactions "
            "order by booking_date"
        ).fetchall()
    return [(bank, flow, Decimal(amount)) for bank, flow, amount in rows]


def other_bank_row() -> dict[str, object]:
    return {
        "transaction_id": "wise:1",
        "bank": "wise",
        "booked_at": datetime(2026, 1, 1),
        "booking_date": date(2026, 1, 1),
        "flow": "income",
        "counterparty": "Kunde",
        "reference": "Rechnung",
        "amount_original": Decimal("10.00"),
        "currency_original": "EUR",
        "amount_eur": Decimal("10.00"),
        "business_amount_eur": Decimal("10.00"),
        "fx_rate": Decimal("1"),
        "fee_eur": Decimal("0.00"),
    }


def test_payment_becomes_negative_business_row(tmp_path: Path) -> None:
    bookings = load_manual_bookings(write(tmp_path / "manual.yaml", BASIC))

    first, second = manual_rows(bookings)

    assert str(first["transaction_id"]).startswith("manual:")
    assert first["bank"] == "scalable"
    assert first["flow"] == "expense"
    assert first["counterparty"] == "SVS"
    assert first["reference"] == "Q1"
    assert first["booking_date"] == date(2026, 2, 28)
    assert first["amount_eur"] == Decimal("-900.50")
    assert first["business_amount_eur"] == Decimal("-900.50")
    assert second["flow"] == "tax"
    assert second["amount_eur"] == Decimal("-1200.00")


def test_refund_is_positive(tmp_path: Path) -> None:
    path = write(
        tmp_path / "manual.yaml",
        "bookings:\n  - {date: 2026-03-01, payee: SVS, amount: 50, type: expense, refund: true}\n",
    )

    row = manual_rows(load_manual_bookings(path))[0]

    assert row["amount_eur"] == Decimal("50.00")
    assert row["business_amount_eur"] == Decimal("50.00")


def test_identical_bookings_stay_distinct(tmp_path: Path) -> None:
    entry = "  - {date: 2026-03-01, payee: SVS, amount: 50, type: expense}\n"
    path = write(tmp_path / "manual.yaml", f"bookings:\n{entry}{entry}")

    rows = manual_rows(load_manual_bookings(path))

    assert len({row["transaction_id"] for row in rows}) == 2


@pytest.mark.parametrize(
    "entry",
    [
        "{date: 2026-03-01, payee: SVS, amount: -50, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: 0, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: 1.234, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: abc, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: .nan, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: 50, type: income}",
        "{date: 2026-03-01, payee: '', amount: 50, type: expense}",
        "{date: gestern, payee: SVS, amount: 50, type: expense}",
        "{date: 2026-03-01, payee: SVS, amount: 50, type: expense, extra: 1}",
    ],
)
def test_invalid_booking_is_rejected(tmp_path: Path, entry: str) -> None:
    path = write(tmp_path / "manual.yaml", f"bookings:\n  - {entry}\n")

    with pytest.raises(ValidationError):
        load_manual_bookings(path)


def test_empty_file_has_no_bookings(tmp_path: Path) -> None:
    assert load_manual_bookings(write(tmp_path / "manual.yaml", "bookings:\n")) == []


def test_edited_booking_replaces_the_old_one(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    path = tmp_path / "manual.yaml"
    entry = "bookings:\n  - {date: 2026-03-01, payee: SVS, amount: %s, type: expense}\n"

    sync_manual_bookings(manual_rows(load_manual_bookings(write(path, entry % "50"))), warehouse)
    sync_manual_bookings(manual_rows(load_manual_bookings(write(path, entry % "60"))), warehouse)

    assert stored(warehouse) == [("scalable", "expense", Decimal("-60"))]


def test_removing_all_bookings_keeps_other_banks(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    load_bank_rows([other_bank_row()], warehouse)
    path = write(tmp_path / "manual.yaml", BASIC)
    sync_manual_bookings(manual_rows(load_manual_bookings(path)), warehouse)

    sync_manual_bookings([], warehouse)

    assert stored(warehouse) == [("wise", "income", Decimal("10"))]


def test_syncing_nothing_without_warehouse_does_not_fail(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"

    assert sync_manual_bookings([], warehouse) == 0
    assert not warehouse.exists()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )


def test_cli_syncs_and_prints_counts_only(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    write(settings.paths.manual_bookings, BASIC)

    assert main(["sync-manual"], settings) == 0

    output = capsys.readouterr().out
    assert "expense: 1" in output
    assert "tax: 1" in output
    assert "SVS" not in output
    assert "900" not in output


def test_cli_missing_file_fails_with_hint(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sync-manual"], settings) == 1

    assert "manual_bookings" in capsys.readouterr().err


def test_cli_invalid_file_does_not_echo_content(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    write(
        settings.paths.manual_bookings,
        "bookings:\n  - {date: 2026-03-01, payee: Secret Payee, amount: -5, type: expense}\n",
    )

    assert main(["sync-manual"], settings) == 1

    captured = capsys.readouterr()
    assert "manual_bookings.yaml" in captured.err
    assert "Secret Payee" not in captured.out + captured.err
