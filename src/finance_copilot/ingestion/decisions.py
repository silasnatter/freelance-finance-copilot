"""Per-booking decisions for vendors with private and business purchases (FR-11)."""

import re
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, NamedTuple

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.ingestion.bank_mapping import BankRowError

CENT = Decimal("0.01")
AMOUNT_FORMATS = (
    r"\d+",
    r"\d+[.,]\d{1,2}",
    r"\d{1,3}(?:\.\d{3})+,\d{1,2}",
)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["business", "private"]
    business_amount_eur: Decimal | None = None


class PendingBooking(NamedTuple):
    transaction_id: str
    booking_date: date
    name: str
    amount_eur: Decimal


def load_decisions(path: Path) -> dict[str, Decision]:
    if not path.is_file():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = content.get("decisions") or {}
    return {str(key): Decision.model_validate(value) for key, value in entries.items()}


def save_decision(path: Path, transaction_id: str, decision: Decision) -> None:
    """Add one decision and replace the file atomically."""
    decisions = load_decisions(path) | {transaction_id: decision}
    entries: dict[str, dict[str, str]] = {}
    for key, value in sorted(decisions.items()):
        entries[key] = {"decision": value.decision}
        if value.business_amount_eur is not None:
            entries[key]["business_amount_eur"] = str(value.business_amount_eur)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        yaml.safe_dump({"decisions": entries}, allow_unicode=True), encoding="utf-8"
    )
    temporary.replace(path)


def apply_decision(row: dict[str, object], decisions: Mapping[str, Decision]) -> dict[str, object]:
    """Resolve an open booking. Other flows are never changed by a decision."""
    transaction_id = str(row["transaction_id"])
    decision = decisions.get(transaction_id)
    if row["flow"] != "needs_review" or decision is None:
        return row
    if decision.decision == "private":
        return row | {"flow": "private", "business_amount_eur": Decimal("0.00")}

    amount = row["amount_eur"]
    if not isinstance(amount, Decimal):
        raise BankRowError(f"invalid decision for booking {transaction_id}")
    share = abs(amount) if decision.business_amount_eur is None else decision.business_amount_eur
    if not share.is_finite() or share <= 0 or share > abs(amount):
        raise BankRowError(f"invalid decision for booking {transaction_id}")
    return row | {"flow": "expense", "business_amount_eur": share if amount > 0 else -share}


def parse_business_amount(raw: str, booking_amount: Decimal) -> Decimal:
    """Parse a typed share such as 89,90 and check it fits the booking."""
    value = raw.strip()
    if not any(re.fullmatch(pattern, value) for pattern in AMOUNT_FORMATS):
        raise ValueError("invalid amount")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    amount = Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount <= 0 or amount > abs(booking_amount):
        raise ValueError("amount out of range")
    return amount


def pending_bookings(warehouse: Path) -> list[PendingBooking]:
    query = """
        select transaction_id, booking_date,
               coalesce(nullif(counterparty, ''), left(reference, 40)), amount_eur
        from raw.bank_transactions
        where flow = 'needs_review'
        order by booking_date, transaction_id
    """
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        tables = connection.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = 'raw' and table_name = 'bank_transactions'"
        ).fetchone()
        if tables is None or tables[0] == 0:
            return []
        return [
            PendingBooking(str(row[0]), row[1], str(row[2]), Decimal(row[3]))
            for row in connection.execute(query).fetchall()
        ]


def store_decision(warehouse: Path, row: Mapping[str, object]) -> None:
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute(
            "update raw.bank_transactions set flow = ?, business_amount_eur = ? "
            "where transaction_id = ?",
            [row["flow"], row["business_amount_eur"], row["transaction_id"]],
        )
