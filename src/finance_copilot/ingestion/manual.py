"""Business payments from accounts without a free export, such as Scalable (FR-02)."""

import datetime as dt
import hashlib
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_copilot.ingestion.bank_csv import load_bank_rows
from finance_copilot.ingestion.bank_mapping import business_amount

CENT = Decimal("0.01")
MANUAL_BANK = "scalable"
ID_PREFIX = "manual:"


class ManualBooking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    date: dt.date
    payee: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, decimal_places=2)
    type: Literal["expense", "tax"]
    note: str = ""
    refund: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def _accept_decimal_comma(cls, value: object) -> object:
        if isinstance(value, str) and "," in value:
            return value.replace(".", "").replace(",", ".")
        return value


def load_manual_bookings(path: Path) -> list[ManualBooking]:
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [ManualBooking.model_validate(entry) for entry in content.get("bookings") or []]


def manual_rows(bookings: list[ManualBooking]) -> list[dict[str, object]]:
    """Normalize bookings. The id ignores the note, so editing a note changes nothing."""
    seen: Counter[tuple[str, ...]] = Counter()
    rows: list[dict[str, object]] = []
    for booking in bookings:
        amount = booking.amount.quantize(CENT, rounding=ROUND_HALF_UP)
        signed = amount if booking.refund else -amount
        key = (
            booking.date.isoformat(),
            booking.payee,
            str(amount),
            booking.type,
            str(booking.refund),
        )
        digest = hashlib.sha256("\x1f".join([*key, str(seen[key])]).encode()).hexdigest()
        seen[key] += 1
        rows.append(
            {
                "transaction_id": f"{ID_PREFIX}{digest[:32]}",
                "bank": MANUAL_BANK,
                "booked_at": dt.datetime.combine(booking.date, dt.time()),
                "booking_date": booking.date,
                "flow": booking.type,
                "counterparty": booking.payee,
                "reference": booking.note,
                "amount_original": signed,
                "currency_original": "EUR",
                "amount_eur": signed,
                "business_amount_eur": business_amount(booking.type, signed),
                "fx_rate": Decimal("1"),
                "fee_eur": Decimal("0.00"),
            }
        )
    return rows


def sync_manual_bookings(rows: list[dict[str, object]], warehouse: Path) -> int:
    """Make the warehouse match the file, including edited and removed bookings."""
    count = load_bank_rows(rows, warehouse)
    if not warehouse.is_file():
        return count
    ids = [str(row["transaction_id"]) for row in rows]
    with duckdb.connect(str(warehouse)) as connection:
        tables = connection.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = 'raw' and table_name = 'bank_transactions'"
        ).fetchone()
        if tables is None or tables[0] == 0:
            return count
        if ids:
            connection.execute(
                "delete from raw.bank_transactions "
                "where starts_with(transaction_id, ?) and not list_contains(?, transaction_id)",
                [ID_PREFIX, ids],
            )
        else:
            connection.execute(
                "delete from raw.bank_transactions where starts_with(transaction_id, ?)",
                [ID_PREFIX],
            )
    return count
