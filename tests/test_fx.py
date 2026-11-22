import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finance_copilot.ingestion.fx import FxRateMissingError, FxRates, save_ecb_rates


def test_chf_is_divided_by_the_ecb_quote(ecb_rates_csv: Path) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    assert rates.to_eur(Decimal("100"), "CHF", date(2026, 3, 2)) == (
        Decimal("125.00"),
        Decimal("0.8"),
    )


def test_eur_is_returned_unchanged(ecb_rates_csv: Path) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    assert rates.to_eur(Decimal("12.34"), "EUR", date(2026, 3, 2)) == (
        Decimal("12.34"),
        Decimal("1"),
    )


def test_weekend_uses_previous_published_rate(ecb_rates_csv: Path) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    _, rate = rates.to_eur(Decimal("1"), "CHF", date(2026, 3, 8))

    assert rate == Decimal("0.5")


def test_not_available_quote_falls_back_to_earlier_rate(ecb_rates_csv: Path) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    _, rate = rates.to_eur(Decimal("1"), "CHF", date(2026, 2, 27))

    assert rate == Decimal("0.9")


def test_eur_amount_rounds_half_up_to_cents(ecb_rates_csv: Path) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    amount, _ = rates.to_eur(Decimal("0.02"), "CHF", date(2026, 3, 2))

    assert amount == Decimal("0.03")


@pytest.mark.parametrize(
    ("currency", "day"),
    [("CHF", date(2026, 2, 19)), ("CHF", date(2026, 3, 11)), ("GBP", date(2026, 3, 2))],
)
def test_missing_or_stale_rate_is_an_error(ecb_rates_csv: Path, currency: str, day: date) -> None:
    rates = FxRates.from_ecb_csv(ecb_rates_csv)

    with pytest.raises(FxRateMissingError):
        rates.to_eur(Decimal("1"), currency, day)


def test_save_ecb_rates_extracts_csv_from_archive(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("eurofxref-hist.csv", "Date,CHF,\n2026-03-02,0.8,\n")
    target = tmp_path / "nested" / "rates.csv"

    save_ecb_rates(buffer.getvalue(), target)

    rates = FxRates.from_ecb_csv(target)
    assert rates.to_eur(Decimal("8"), "CHF", date(2026, 3, 2))[0] == Decimal("10.00")
