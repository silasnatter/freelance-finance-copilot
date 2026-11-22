import csv
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_mapping import load_bank_mapping, normalize_row
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import (
    BusinessRules,
    load_ledger_mapping,
    parse_ledger_row,
)
from finance_copilot.ingestion.reserve import (
    ReserveSettings,
    load_reserve_settings,
    store_reserve_settings,
)
from finance_copilot.ingestion.typed_export import load_typed_mapping, parse_typed_row

RowFactory = Callable[..., dict[str, str]]
LEDGER = load_ledger_mapping(PROJECT_ROOT / "config" / "banks" / "raiffeisen.yaml")
TYPED = load_typed_mapping(PROJECT_ROOT / "config" / "banks" / "trade_republic.yaml")
WISE = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")
RULES = BusinessRules(expense=("SVS", "Hetzner"), reserve_paid=("SVS", "Nur Topf"))


def line(text: str) -> list[str]:
    return ["01.03.2026", text, "01.03.2026", "-100,00", "EUR", "01.03.2026 10:00:00:000"]


def typed_row(name: str) -> dict[str, str]:
    columns = [
        "fee",
        "original_amount",
        "original_currency",
        "fx_rate",
        "counterparty_name",
        "description",
        "payment_reference",
    ]
    return dict.fromkeys(columns, "") | {
        "transaction_id": "tr-1",
        "datetime": "2026-03-01T10:00:00Z",
        "date": "2026-03-01",
        "type": "CARD_TRANSACTION",
        "name": name,
        "amount": "-10.00",
        "currency": "EUR",
    }


@pytest.fixture
def rates(ecb_rates_csv: Path) -> FxRates:
    return FxRates.from_ecb_csv(ecb_rates_csv)


def test_reserve_settings_are_loaded(tmp_path: Path) -> None:
    path = tmp_path / "reserve.yaml"
    path.write_text(
        "start_date: 2026-01-01\nstart_balance_eur: '10.000,50'\nincome_share: 0.4\n",
        encoding="utf-8",
    )

    assert load_reserve_settings(path) == ReserveSettings(
        start_date=date(2026, 1, 1),
        start_balance_eur=Decimal("10000.50"),
        income_share=Decimal("0.4"),
    )


def test_income_share_defaults_to_half(tmp_path: Path) -> None:
    path = tmp_path / "reserve.yaml"
    path.write_text("start_date: 2026-01-01\nstart_balance_eur: 100\n", encoding="utf-8")

    assert load_reserve_settings(path).income_share == Decimal("0.5")


def test_missing_file_counts_all_income_from_zero(tmp_path: Path) -> None:
    result = load_reserve_settings(tmp_path / "missing.yaml")

    assert result.start_balance_eur == Decimal("0")
    assert result.income_share == Decimal("0.5")
    assert result.start_date <= date(2020, 1, 1)


@pytest.mark.parametrize(
    "body",
    [
        "start_date: 2026-01-01\nstart_balance_eur: -1\n",
        "start_date: 2026-01-01\nstart_balance_eur: 1.234\n",
        "start_date: 2026-01-01\nstart_balance_eur: 1\nincome_share: 0\n",
        "start_date: 2026-01-01\nstart_balance_eur: 1\nincome_share: 1.1\n",
        "start_date: gestern\nstart_balance_eur: 1\n",
        "start_date: 2026-01-01\nstart_balance_eur: 1\nunknown: 1\n",
    ],
)
def test_invalid_reserve_settings_are_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "reserve.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_reserve_settings(path)


def test_stored_settings_replace_the_previous_row(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    first = ReserveSettings(start_date=date(2026, 1, 1), start_balance_eur=Decimal("1.00"))
    second = ReserveSettings(start_date=date(2026, 2, 1), start_balance_eur=Decimal("2.00"))

    store_reserve_settings(first, warehouse)
    store_reserve_settings(second, warehouse)

    with duckdb.connect(str(warehouse), read_only=True) as connection:
        rows = connection.execute(
            "select start_date, start_balance_eur, income_share from raw.reserve_settings"
        ).fetchall()
    assert rows == [(date(2026, 2, 1), Decimal("2.00"), Decimal("0.5000"))]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Zahlungsempfänger: SVS", True),
        ("Zahlungsempfänger: Hetzner", False),
        ("Zahlungsempfänger: Nur Topf", False),
    ],
)
def test_ledger_marks_expenses_paid_from_the_pot(rates: FxRates, text: str, expected: bool) -> None:
    row = parse_ledger_row(line(text), LEDGER, rates, frozenset(), RULES, row_number=1)

    assert row["paid_from_reserve"] is expected


def test_trade_republic_marks_expenses_paid_from_the_pot(rates: FxRates) -> None:
    marked = parse_typed_row(typed_row("SVS"), TYPED, rates, frozenset(), RULES)
    other = parse_typed_row(typed_row("Hetzner"), TYPED, rates, frozenset(), RULES)

    assert marked["paid_from_reserve"] is True
    assert other["paid_from_reserve"] is False


def test_wise_rows_are_not_paid_from_the_pot(wise_row: RowFactory, rates: FxRates) -> None:
    result = normalize_row(wise_row(), WISE, rates)

    assert result is not None
    assert result["paid_from_reserve"] is False


@pytest.fixture
def settings(tmp_path: Path, ecb_rates_csv: Path) -> Settings:
    loaded = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    loaded.paths.fx_rates.parent.mkdir(parents=True)
    loaded.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    loaded.paths.reserve.parent.mkdir(parents=True, exist_ok=True)
    return loaded


def write_export(path: Path) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file, delimiter=";").writerow(line("Zahlungsempfänger: SVS"))
    return path


def test_ingest_stores_private_settings_without_printing_them(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.reserve.write_text(
        "start_date: 2026-01-01\nstart_balance_eur: 12345.67\n", encoding="utf-8"
    )
    source = write_export(tmp_path / "bank.csv")

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 0

    assert "12345" not in capsys.readouterr().out
    with duckdb.connect(str(settings.paths.warehouse), read_only=True) as connection:
        stored = connection.execute("select start_balance_eur from raw.reserve_settings").fetchone()
    assert stored == (Decimal("12345.67"),)


def test_invalid_settings_stop_the_import_without_echoing_them(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.reserve.write_text(
        "start_date: 2026-01-01\nstart_balance_eur: -98765\n", encoding="utf-8"
    )
    source = write_export(tmp_path / "bank.csv")

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 1

    captured = capsys.readouterr()
    assert "reserve.yaml" in captured.err
    assert "98765" not in captured.out + captured.err
    assert not settings.paths.warehouse.exists()


def test_demo_uses_public_demo_settings(settings: Settings) -> None:
    assert main(["demo"], settings) == 0

    demo = settings.paths.demo_data / "warehouse.duckdb"
    with duckdb.connect(str(demo), read_only=True) as connection:
        stored = connection.execute(
            "select start_balance_eur, income_share from raw.reserve_settings"
        ).fetchone()
    assert stored == (Decimal("5000.00"), Decimal("0.5000"))
