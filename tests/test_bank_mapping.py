from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finance_copilot.config import PROJECT_ROOT
from finance_copilot.ingestion.bank_mapping import (
    BankRowError,
    load_bank_mapping,
    normalize_row,
)
from finance_copilot.ingestion.fx import FxRates

RowFactory = Callable[..., dict[str, str]]
MAPPING = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")


def test_income_in_chf_is_gross_in_eur_with_separate_fee(
    wise_row: RowFactory, ecb_rates_csv: Path
) -> None:
    row = wise_row(
        Direction="IN",
        **{
            "Source name": "Kunde AG",
            "Source currency": "CHF",
            "Source amount (after fees)": "1005.00",
            "Target name": "Demo Freelancer",
            "Target amount (after fees)": "1000.00",
            "Target currency": "CHF",
            "Target fee amount": "5.00",
            "Target fee currency": "CHF",
            "Source fee amount": "",
            "Source fee currency": "",
        },
    )

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv))

    assert result is not None
    assert result["transaction_id"] == "wise:TRANSFER-1"
    assert result["flow"] == "income"
    assert result["counterparty"] == "Kunde AG"
    assert result["amount_original"] == Decimal("1005.00")
    assert result["currency_original"] == "CHF"
    assert result["amount_eur"] == Decimal("1256.25")
    assert result["fx_rate"] == Decimal("0.8")
    assert result["fee_eur"] == Decimal("6.25")
    assert result["booked_at"] == datetime(2026, 3, 2, 10, 0, 0)
    assert result["booking_date"] == date(2026, 3, 2)


def test_expense_is_negative_and_excludes_fee(wise_row: RowFactory, ecb_rates_csv: Path) -> None:
    row = wise_row(**{"Source fee amount": "1.50"})

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv))

    assert result is not None
    assert result["flow"] == "expense"
    assert result["counterparty"] == "Hosting GmbH"
    assert result["reference"] == "Server March"
    assert result["amount_eur"] == Decimal("-50.00")
    assert result["fee_eur"] == Decimal("1.50")


def test_chf_funded_expense_uses_paid_eur_amount_and_converts_fee(
    wise_row: RowFactory, ecb_rates_csv: Path
) -> None:
    row = wise_row(
        **{
            "Source currency": "CHF",
            "Source amount (after fees)": "40.00",
            "Source fee amount": "0.80",
            "Source fee currency": "CHF",
        }
    )

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv))

    assert result is not None
    assert result["amount_eur"] == Decimal("-50.00")
    assert result["fx_rate"] == Decimal("1")
    assert result["fee_eur"] == Decimal("1.00")


def test_neutral_row_is_a_conversion(wise_row: RowFactory, ecb_rates_csv: Path) -> None:
    row = wise_row(Direction="NEUTRAL", **{"Target name": "Demo Freelancer"})

    result = normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv))

    assert result is not None
    assert result["flow"] == "conversion"


def test_row_with_unaccepted_status_is_skipped(wise_row: RowFactory, ecb_rates_csv: Path) -> None:
    row = wise_row(Status="CANCELLED")

    assert normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"Direction": "SIDEWAYS"},
        {"Target amount (after fees)": "abc"},
        {"Finished on": "02.03.2026"},
        {"Source fee amount": "1.00", "Source fee currency": ""},
    ],
)
def test_malformed_row_error_names_id_but_not_content(
    wise_row: RowFactory, ecb_rates_csv: Path, overrides: dict[str, str]
) -> None:
    row = wise_row(Reference="SECRET-REFERENCE", **overrides)

    with pytest.raises(BankRowError) as error:
        normalize_row(row, MAPPING, FxRates.from_ecb_csv(ecb_rates_csv))

    assert "TRANSFER-1" in str(error.value)
    assert "SECRET-REFERENCE" not in str(error.value)
    assert "Hosting GmbH" not in str(error.value)
