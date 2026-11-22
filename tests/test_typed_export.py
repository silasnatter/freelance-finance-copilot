import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_mapping import BankRowError
from finance_copilot.ingestion.decisions import Decision
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import BusinessRules
from finance_copilot.ingestion.typed_export import (
    load_typed_mapping,
    parse_typed_row,
    read_typed_csv,
)

COLUMNS = [
    "datetime",
    "date",
    "account_type",
    "category",
    "type",
    "asset_class",
    "name",
    "symbol",
    "shares",
    "price",
    "amount",
    "fee",
    "tax",
    "currency",
    "original_amount",
    "original_currency",
    "fx_rate",
    "description",
    "transaction_id",
    "counterparty_name",
    "counterparty_iban",
    "payment_reference",
    "mcc_code",
]
MAPPING = load_typed_mapping(PROJECT_ROOT / "config" / "banks" / "trade_republic.yaml")
RULES = BusinessRules(expense=("Hetzner",), mixed=("Mediamarkt",), tax=("Finanzamt",))
OWN = frozenset({"demo freelancer"})


def row(**overrides: str) -> dict[str, str]:
    values = dict.fromkeys(COLUMNS, "")
    values.update(
        {
            "datetime": "2026-03-01T23:30:00.123456Z",
            "date": "2026-03-02",
            "account_type": "DEFAULT",
            "category": "CASH",
            "type": "CARD_TRANSACTION",
            "name": "Bäckerei Huber",
            "amount": "-12.50",
            "currency": "EUR",
            "transaction_id": "tr-1",
        }
    )
    values.update(overrides)
    return values


@pytest.fixture
def rates(ecb_rates_csv: Path) -> FxRates:
    return FxRates.from_ecb_csv(ecb_rates_csv)


def parse(values: dict[str, str], rates: FxRates) -> dict[str, object]:
    return parse_typed_row(values, MAPPING, rates, OWN, RULES)


def write_export(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_card_payment_is_private_by_default(rates: FxRates) -> None:
    result = parse(row(), rates)

    assert result["transaction_id"] == "trade_republic:tr-1"
    assert result["flow"] == "private"
    assert result["counterparty"] == "Bäckerei Huber"
    assert result["amount_eur"] == Decimal("-12.50")
    assert result["business_amount_eur"] == Decimal("0.00")
    assert result["booking_date"] == date(2026, 3, 2)
    assert result["booked_at"] == datetime(2026, 3, 1, 23, 30, 0, 123456)


@pytest.mark.parametrize(
    "stamp", ["2026-03-01T23:30:00.123456Z", "2026-03-01T23:30:00.123Z", "2026-03-01T23:30:00Z"]
)
def test_all_export_timestamp_formats_are_read(rates: FxRates, stamp: str) -> None:
    result = parse(row(datetime=stamp), rates)

    booked_at = result["booked_at"]
    assert isinstance(booked_at, datetime)
    assert booked_at.replace(microsecond=0) == datetime(2026, 3, 1, 23, 30, 0)
    assert booked_at.tzinfo is None


@pytest.mark.parametrize(
    ("merchant", "flow", "business"),
    [
        ("HETZNER ONLINE", "expense", "-12.50"),
        ("MEDIAMARKT Wien", "needs_review", "0.00"),
        ("Finanzamt Österreich", "tax", "-12.50"),
    ],
)
def test_rules_apply_to_card_payments(
    rates: FxRates, merchant: str, flow: str, business: str
) -> None:
    result = parse(row(name=merchant), rates)

    assert result["flow"] == flow
    assert result["business_amount_eur"] == Decimal(business)


def test_card_refund_keeps_positive_sign(rates: FxRates) -> None:
    result = parse(row(name="Hetzner", amount="5.00"), rates)

    assert result["flow"] == "expense"
    assert result["business_amount_eur"] == Decimal("5.00")


def test_transfer_to_own_account_is_a_transfer(rates: FxRates) -> None:
    values = row(type="TRANSFER_INSTANT_OUTBOUND", name="", counterparty_name="DEMO  Freelancer")

    assert parse(values, rates)["flow"] == "transfer"


def test_counterparty_name_wins_and_description_is_the_fallback(rates: FxRates) -> None:
    named = parse(row(counterparty_name="Empfänger KG", name="Anderer Name"), rates)
    described = parse(row(name="", description="Text only"), rates)

    assert named["counterparty"] == "Empfänger KG"
    assert described["counterparty"] == "Text only"
    assert described["reference"] == "Text only"


def test_payment_reference_is_preferred(rates: FxRates) -> None:
    result = parse(row(payment_reference="Rechnung 7", description="Text"), rates)

    assert result["reference"] == "Rechnung 7"


@pytest.mark.parametrize(
    "booking_type",
    [
        "BUY",
        "SELL",
        "DIVIDEND",
        "EARNINGS",
        "INTEREST_PAYMENT",
        "BENEFITS_SAVEBACK",
        "TAX_OPTIMIZATION",
    ],
)
def test_investments_never_match_business_rules(rates: FxRates, booking_type: str) -> None:
    result = parse(row(type=booking_type, name="Mediamarkt Hetzner Finanzamt"), rates)

    assert result["flow"] == "investment"
    assert result["business_amount_eur"] == Decimal("0.00")


def test_delivery_without_amount_is_zero(rates: FxRates) -> None:
    result = parse(row(type="FREE_RECEIPT", category="DELIVERY", amount=""), rates)

    assert result["flow"] == "investment"
    assert result["amount_eur"] == Decimal("0.00")


def test_gift_is_private_even_if_name_matches_rule(rates: FxRates) -> None:
    assert parse(row(type="GIFT", name="Hetzner"), rates)["flow"] == "private"


def test_foreign_card_payment_keeps_original_amount_with_sign(rates: FxRates) -> None:
    values = row(
        type="CARD_TRANSACTION_INTERNATIONAL",
        amount="-9.20",
        original_amount="10.00",
        original_currency="USD",
        fx_rate="1.087",
    )

    result = parse(values, rates)

    assert result["amount_eur"] == Decimal("-9.20")
    assert result["amount_original"] == Decimal("-10.00")
    assert result["currency_original"] == "USD"
    assert result["fx_rate"] == Decimal("1.087")


def test_fee_is_stored_as_positive_amount(rates: FxRates) -> None:
    assert parse(row(fee="-1.00"), rates)["fee_eur"] == Decimal("1.00")


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "NEW_TYPE"},
        {"amount": ""},
        {"amount": "abc"},
        {"amount": "NaN"},
        {"currency": "USD"},
        {"date": "02.03.2026"},
        {"datetime": "gestern"},
        {"transaction_id": ""},
        {"fee": "abc"},
        {"original_amount": "abc", "original_currency": "USD"},
    ],
)
def test_malformed_row_error_has_no_content(rates: FxRates, overrides: dict[str, str]) -> None:
    with pytest.raises(BankRowError) as error:
        parse(row(**overrides), rates)

    assert "Bäckerei" not in str(error.value)


def test_decision_is_applied_when_reading(tmp_path: Path, rates: FxRates) -> None:
    source = write_export(tmp_path / "tr.csv", [row(name="Mediamarkt")])
    decisions = {
        "trade_republic:tr-1": Decision(decision="business", business_amount_eur=Decimal("2.50"))
    }

    result = read_typed_csv(source, MAPPING, rates, OWN, RULES, decisions)

    assert result[0]["flow"] == "expense"
    assert result[0]["business_amount_eur"] == Decimal("-2.50")


@pytest.fixture
def settings(tmp_path: Path, ecb_rates_csv: Path) -> Settings:
    loaded = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    loaded.paths.fx_rates.parent.mkdir(parents=True)
    loaded.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    loaded.paths.business_rules.parent.mkdir(parents=True, exist_ok=True)
    loaded.paths.business_rules.write_text("mixed: [Mediamarkt]\n", encoding="utf-8")
    return loaded


def test_cli_import_is_repeatable_and_prints_counts_only(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_export(
        tmp_path / "tr.csv",
        [
            row(),
            row(transaction_id="tr-2", name="Mediamarkt"),
            row(transaction_id="tr-3", type="BUY", name="Some ETF"),
        ],
    )
    command = ["ingest", "--bank", "trade_republic", "--file", str(source)]

    assert main(command, settings) == 0
    assert main(command, settings) == 0

    output = capsys.readouterr().out
    assert "investment: 1" in output
    assert "needs_review: 1" in output
    assert "private: 1" in output
    assert "Bäckerei" not in output
    with duckdb.connect(str(settings.paths.warehouse), read_only=True) as connection:
        assert connection.execute("select count(*) from raw.bank_transactions").fetchone() == (3,)
