"""Normalize bank CSV rows through a YAML mapping (FR-02)."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.ingestion.fx import FxRateMissingError, FxRates


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StatusRule(_Model):
    column: str
    accepted: tuple[str, ...]


class DateRule(_Model):
    column: str
    format: str


class FlowRule(_Model):
    flow: Literal["income", "expense", "conversion"]
    sign: Literal[-1, 1]
    amount: str
    currency: str
    counterparty: str
    add_fees_to_amount: bool = False


class FeeRule(_Model):
    amount: str
    currency: str


class BankMapping(_Model):
    bank: str
    id: str
    status: StatusRule
    booked_at: DateRule
    direction: str
    reference: str
    flows: dict[str, FlowRule]
    fees: tuple[FeeRule, ...] = ()


class BankRowError(ValueError):
    """A row is malformed. The message never contains financial content."""


def load_bank_mapping(path: Path) -> BankMapping:
    return BankMapping.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def business_amount(flow: str, amount_eur: Decimal) -> Decimal:
    """Return the signed EUR amount that counts for the business."""
    return amount_eur if flow in ("income", "expense", "tax") else Decimal("0.00")


def normalize_name(value: str) -> str:
    """Make account holder names comparable across spelling and spacing."""
    return " ".join(value.split()).casefold()


def load_own_names(path: Path) -> frozenset[str]:
    """Read the private list of own account holder names, if it exists."""
    if not path.is_file():
        return frozenset()
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return frozenset(normalize_name(str(name)) for name in content.get("names") or [])


def _decimal(value: str, field: str, row_id: str, bank: str) -> Decimal:
    try:
        parsed = Decimal(value.strip() or "0")
    except InvalidOperation:
        raise BankRowError(f"{bank} row {row_id}: invalid {field}") from None
    if not parsed.is_finite():
        raise BankRowError(f"{bank} row {row_id}: invalid {field}")
    return parsed


def normalize_row(
    row: Mapping[str, str],
    mapping: BankMapping,
    rates: FxRates,
    own_names: frozenset[str] = frozenset(),
) -> dict[str, object] | None:
    """Return a normalized transaction, or None if its status is not accepted."""
    if row[mapping.status.column] not in mapping.status.accepted:
        return None

    bank = mapping.bank
    row_id = row[mapping.id].strip()
    if not row_id:
        raise BankRowError(f"{bank} row without id")
    rule = mapping.flows.get(row[mapping.direction])
    if rule is None:
        raise BankRowError(f"{bank} row {row_id}: unknown direction")
    try:
        booked_at = datetime.strptime(
            row[mapping.booked_at.column].strip(), mapping.booked_at.format
        )
    except ValueError:
        raise BankRowError(f"{bank} row {row_id}: invalid booking date") from None

    booking_date = booked_at.date()
    amount = _decimal(row[rule.amount], "amount", row_id, bank)
    currency = row[rule.currency].strip()
    fee_eur = Decimal("0.00")

    try:
        for fee in mapping.fees:
            fee_amount = _decimal(row[fee.amount], "fee", row_id, bank)
            if fee_amount == 0:
                continue
            fee_currency = row[fee.currency].strip()
            if not fee_currency:
                raise BankRowError(f"{bank} row {row_id}: fee without currency")
            if rule.add_fees_to_amount:
                if fee_currency != currency:
                    raise BankRowError(f"{bank} row {row_id}: fee in different currency")
                amount += fee_amount
            fee_eur += rates.to_eur(fee_amount, fee_currency, booking_date)[0]
        amount_eur, fx_rate = rates.to_eur(amount, currency, booking_date)
    except FxRateMissingError as error:
        raise BankRowError(f"{bank} row {row_id}: {error}") from None

    counterparty = row[rule.counterparty].strip()
    is_own_account = rule.flow != "conversion" and normalize_name(counterparty) in own_names
    flow = "transfer" if is_own_account else rule.flow

    return {
        "transaction_id": f"{bank}:{row_id}",
        "bank": bank,
        "booked_at": booked_at,
        "booking_date": booking_date,
        "flow": flow,
        "counterparty": counterparty,
        "reference": row[mapping.reference].strip(),
        "amount_original": rule.sign * amount,
        "currency_original": currency,
        "amount_eur": rule.sign * amount_eur,
        "business_amount_eur": business_amount(flow, rule.sign * amount_eur),
        "fx_rate": fx_rate,
        "fee_eur": fee_eur,
    }
