"""Convert amounts to EUR with ECB euro reference rates."""

import csv
import io
import zipfile
from bisect import bisect_right
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Self

ECB_HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
MAX_RATE_AGE = timedelta(days=7)
CENT = Decimal("0.01")


class FxRateMissingError(ValueError):
    """No usable ECB rate exists for a currency and date."""


class FxRates:
    """ECB quotes, expressed as units of foreign currency per 1 EUR."""

    def __init__(self, quotes: dict[str, list[tuple[date, Decimal]]]) -> None:
        self._quotes = {currency: sorted(values) for currency, values in quotes.items()}

    @classmethod
    def from_ecb_csv(cls, path: Path) -> Self:
        quotes: dict[str, list[tuple[date, Decimal]]] = {}
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                day = date.fromisoformat(row["Date"].strip())
                for currency, raw in row.items():
                    name = (currency or "").strip()
                    if name in ("", "Date") or not isinstance(raw, str):
                        continue
                    try:
                        quote = Decimal(raw.strip())
                    except InvalidOperation:
                        continue
                    if quote.is_finite() and quote > 0:
                        quotes.setdefault(name, []).append((day, quote))
        return cls(quotes)

    def to_eur(self, amount: Decimal, currency: str, on: date) -> tuple[Decimal, Decimal]:
        """Return the EUR amount in cents and the applied rate."""
        if currency == "EUR":
            return amount.quantize(CENT, rounding=ROUND_HALF_UP), Decimal("1")
        rate = self._rate(currency, on)
        return (amount / rate).quantize(CENT, rounding=ROUND_HALF_UP), rate

    def _rate(self, currency: str, on: date) -> Decimal:
        values = self._quotes.get(currency, [])
        index = bisect_right([day for day, _ in values], on) - 1
        if index < 0 or on - values[index][0] > MAX_RATE_AGE:
            raise FxRateMissingError(f"No ECB rate for {currency} on {on.isoformat()}")
        return values[index][1]


def save_ecb_rates(archive: bytes, target: Path) -> None:
    """Extract the ECB history CSV from its zip archive."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        content = bundle.read("eurofxref-hist.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
