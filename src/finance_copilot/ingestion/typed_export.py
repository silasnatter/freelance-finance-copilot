"""Import exports that label each booking with a type, such as Trade Republic (FR-02).

Cash movements are private unless a rule matches. Investments never reach the
business rules, so a security named like a vendor cannot count as a purchase.
"""

import csv
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.ingestion.bank_mapping import BankRowError, business_amount
from finance_copilot.ingestion.decisions import Decision, apply_decision
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import BusinessRules, classify_by_rules

CENT = Decimal("0.01")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TypedColumns(_Model):
    id: str
    datetime: str
    date: str
    type: str
    amount: str
    fee: str
    currency: str
    original_amount: str
    original_currency: str
    fx_rate: str
    counterparty: tuple[str, ...]
    reference: tuple[str, ...]


class TypedMapping(_Model):
    bank: str
    format: Literal["typed_export"]
    columns: TypedColumns
    rule_based_types: frozenset[str]
    investment_types: frozenset[str]
    private_types: frozenset[str]
    amountless_types: frozenset[str] = frozenset()


def is_typed_mapping(path: Path) -> bool:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return bool(content.get("format") == "typed_export")


def load_typed_mapping(path: Path) -> TypedMapping:
    return TypedMapping.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _decimal(value: str, field: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        raise BankRowError(f"{label}: invalid {field}") from None
    if not parsed.is_finite():
        raise BankRowError(f"{label}: invalid {field}")
    return parsed


def _first(row: Mapping[str, str], columns: Sequence[str]) -> str:
    return next((row[column].strip() for column in columns if row[column].strip()), "")


def _booked_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _flow(
    booking_type: str,
    counterparty: str,
    reference: str,
    mapping: TypedMapping,
    own_names: frozenset[str],
    rules: BusinessRules,
    label: str,
) -> str:
    if booking_type in mapping.rule_based_types:
        return classify_by_rules(counterparty, reference, own_names, rules)
    if booking_type in mapping.investment_types:
        return "investment"
    if booking_type in mapping.private_types:
        return "private"
    shown = booking_type if re.fullmatch(r"[A-Z0-9_]{1,50}", booking_type) else "(invalid)"
    raise BankRowError(f"{label}: unknown booking type {shown}")


def parse_typed_row(
    row: Mapping[str, str],
    mapping: TypedMapping,
    rates: FxRates,
    own_names: frozenset[str],
    rules: BusinessRules,
) -> dict[str, object]:
    """Normalize one row. Errors name the booking id, never its content."""
    bank = mapping.bank
    columns = mapping.columns
    row_id = row[columns.id].strip()
    if not row_id:
        raise BankRowError(f"{bank} row without id")
    label = f"{bank} row {row_id}"

    booking_type = row[columns.type].strip()
    counterparty = _first(row, columns.counterparty)
    reference = _first(row, columns.reference)
    flow = _flow(booking_type, counterparty, reference, mapping, own_names, rules, label)

    try:
        booking_date = date.fromisoformat(row[columns.date].strip())
        booked_at = _booked_at(row[columns.datetime])
    except ValueError:
        raise BankRowError(f"{label}: invalid date") from None

    currency = row[columns.currency].strip()
    if currency != "EUR":
        raise BankRowError(f"{label}: unsupported account currency")
    raw_amount = row[columns.amount].strip()
    if not raw_amount and booking_type in mapping.amountless_types:
        amount = Decimal("0.00")
    else:
        amount = _decimal(raw_amount, "amount", label)
    amount_eur = amount.quantize(CENT, rounding=ROUND_HALF_UP)

    amount_original = amount
    currency_original = currency
    fx_rate = Decimal("1")
    if original_currency := row[columns.original_currency].strip():
        original = _decimal(row[columns.original_amount], "original amount", label)
        amount_original = abs(original).copy_sign(amount)
        currency_original = original_currency
        if raw_rate := row[columns.fx_rate].strip():
            fx_rate = _decimal(raw_rate, "exchange rate", label)

    raw_fee = row[columns.fee].strip()
    fee = abs(_decimal(raw_fee, "fee", label)) if raw_fee else Decimal("0.00")

    return {
        "transaction_id": f"{bank}:{row_id}",
        "bank": bank,
        "booked_at": booked_at,
        "booking_date": booking_date,
        "flow": flow,
        "counterparty": counterparty,
        "reference": reference,
        "amount_original": amount_original,
        "currency_original": currency_original,
        "amount_eur": amount_eur,
        "business_amount_eur": business_amount(flow, amount_eur),
        "fx_rate": fx_rate,
        "fee_eur": fee,
    }


def read_typed_csv(
    path: Path,
    mapping: TypedMapping,
    rates: FxRates,
    own_names: frozenset[str],
    rules: BusinessRules,
    decisions: Mapping[str, Decision] | None = None,
) -> list[dict[str, object]]:
    columns = mapping.columns
    required = {
        columns.id,
        columns.datetime,
        columns.date,
        columns.type,
        columns.amount,
        columns.fee,
        columns.currency,
        columns.original_amount,
        columns.original_currency,
        columns.fx_rate,
        *columns.counterparty,
        *columns.reference,
    }
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not required <= set(reader.fieldnames or ()):
            raise BankRowError(f"{mapping.bank} export: expected columns are missing")
        return [
            apply_decision(parse_typed_row(row, mapping, rates, own_names, rules), decisions or {})
            for row in reader
        ]
