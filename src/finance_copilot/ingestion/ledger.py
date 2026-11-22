"""Import signed-amount bank exports of mixed-use accounts (FR-02).

Rows are private unless a business rule matches, so private spending cannot
reach revenue or profit by accident.
"""

import csv
import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.ingestion.bank_mapping import BankRowError, business_amount, normalize_name
from finance_copilot.ingestion.decisions import Decision, apply_decision
from finance_copilot.ingestion.fx import FxRateMissingError, FxRates


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LedgerColumns(_Model):
    booking_date: int
    text: int
    value_date: int
    amount: int
    currency: int
    timestamp: int


class LedgerMapping(_Model):
    bank: str
    format: Literal["signed_ledger"]
    delimiter: str
    has_header: bool
    columns: LedgerColumns
    date_format: str
    timestamp_format: str
    decimal_separator: str
    thousands_separator: str
    text_labels: tuple[str, ...]
    incoming_counterparty: tuple[str, ...]
    outgoing_counterparty: tuple[str, ...]
    reference: tuple[str, ...]


class BusinessRules(_Model):
    income: tuple[str, ...] = ()
    expense: tuple[str, ...] = ()
    tax: tuple[str, ...] = ()
    mixed: tuple[str, ...] = ()
    reserve_paid: tuple[str, ...] = ()


def is_ledger_mapping(path: Path) -> bool:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return bool(content.get("format") == "signed_ledger")


def load_ledger_mapping(path: Path) -> LedgerMapping:
    return LedgerMapping.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_business_rules(path: Path) -> BusinessRules:
    """Read the private rules. Without a file, every row stays private."""
    if not path.is_file():
        return BusinessRules()
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return BusinessRules.model_validate({key: value or () for key, value in content.items()})


def _text_fields(text: str, labels: Sequence[str]) -> dict[str, str]:
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    matches = list(re.finditer(rf"(?<![\w-])({alternatives}):", text))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields.setdefault(match.group(1), text[match.end() : end].strip(" |,;\t\r\n"))
    return fields


def _first(fields: dict[str, str], labels: Sequence[str]) -> str:
    return next((fields[label] for label in labels if fields.get(label)), "")


def _matches(terms: Sequence[str], haystack: str) -> bool:
    for term in terms:
        needle = normalize_name(term)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            return True
    return False


def classify_by_rules(
    counterparty: str, text: str, own_names: frozenset[str], rules: BusinessRules
) -> str:
    if counterparty and normalize_name(counterparty) in own_names:
        return "transfer"
    haystack = normalize_name(counterparty or text)
    ordered = (
        ("needs_review", rules.mixed),
        ("tax", rules.tax),
        ("expense", rules.expense),
        ("income", rules.income),
    )
    for flow, terms in ordered:
        if _matches(terms, haystack):
            return flow
    return "private"


def is_paid_from_reserve(flow: str, counterparty: str, text: str, rules: BusinessRules) -> bool:
    """Mark expenses such as SVS that are paid from the safety pot."""
    return flow == "expense" and _matches(rules.reserve_paid, normalize_name(counterparty or text))


def _amount(raw: str, mapping: LedgerMapping) -> Decimal:
    thousands = re.escape(mapping.thousands_separator)
    decimal = re.escape(mapping.decimal_separator)
    value = raw.strip()
    if not re.fullmatch(rf"[+-]?\d+(?:{thousands}\d{{3}})*{decimal}\d{{1,2}}", value):
        raise ValueError
    return Decimal(
        value.replace(mapping.thousands_separator, "").replace(mapping.decimal_separator, ".")
    )


def parse_ledger_row(
    fields: Sequence[str],
    mapping: LedgerMapping,
    rates: FxRates,
    own_names: frozenset[str],
    rules: BusinessRules,
    row_number: int,
    occurrence: int = 0,
) -> dict[str, object]:
    """Normalize one row. Errors name the row number, never its content."""
    bank = mapping.bank
    columns = mapping.columns
    if len(fields) <= max(columns.model_dump().values()):
        raise BankRowError(f"{bank} row {row_number}: unexpected column count")
    try:
        booking_date = datetime.strptime(
            fields[columns.booking_date].strip(), mapping.date_format
        ).date()
        booked_at = datetime.strptime(fields[columns.timestamp].strip(), mapping.timestamp_format)
    except ValueError:
        raise BankRowError(f"{bank} row {row_number}: invalid date") from None
    try:
        amount = _amount(fields[columns.amount], mapping)
    except ValueError:
        raise BankRowError(f"{bank} row {row_number}: invalid amount") from None

    currency = fields[columns.currency].strip()
    try:
        amount_eur, fx_rate = rates.to_eur(amount, currency, booking_date)
    except FxRateMissingError:
        raise BankRowError(f"{bank} row {row_number}: no exchange rate") from None

    text = fields[columns.text].strip()
    labeled = _text_fields(text, mapping.text_labels)
    labels = mapping.incoming_counterparty if amount >= 0 else mapping.outgoing_counterparty
    counterparty = _first(labeled, labels)
    digest = hashlib.sha256("\x1f".join([*fields, str(occurrence)]).encode()).hexdigest()
    flow = classify_by_rules(counterparty, text, own_names, rules)

    return {
        "transaction_id": f"{bank}:{digest[:32]}",
        "bank": bank,
        "booked_at": booked_at,
        "booking_date": booking_date,
        "flow": flow,
        "counterparty": counterparty,
        "reference": _first(labeled, mapping.reference) or text,
        "amount_original": amount,
        "currency_original": currency,
        "amount_eur": amount_eur,
        "business_amount_eur": business_amount(flow, amount_eur),
        "paid_from_reserve": is_paid_from_reserve(flow, counterparty, text, rules),
        "fx_rate": fx_rate,
        "fee_eur": Decimal("0.00"),
    }


def read_ledger_csv(
    path: Path,
    mapping: LedgerMapping,
    rates: FxRates,
    own_names: frozenset[str],
    rules: BusinessRules,
    decisions: Mapping[str, Decision] | None = None,
) -> list[dict[str, object]]:
    seen: Counter[tuple[str, ...]] = Counter()
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file, delimiter=mapping.delimiter)
        if mapping.has_header:
            next(reader, None)
        for row_number, fields in enumerate(reader, start=1):
            key = tuple(fields)
            parsed = parse_ledger_row(
                fields, mapping, rates, own_names, rules, row_number, occurrence=seen[key]
            )
            rows.append(apply_decision(parsed, decisions or {}))
            seen[key] += 1
    return rows


def top_private_counterparties(warehouse: Path, limit: int) -> list[tuple[str, int]]:
    """Most frequent private rows, to help find missing business rules."""
    query = """
        select coalesce(nullif(counterparty, ''), left(reference, 40)) as name, count(*) as rows
        from raw.bank_transactions
        where flow = 'private'
        group by 1
        order by rows desc, name
        limit ?
    """
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        return [
            (str(name), int(rows)) for name, rows in connection.execute(query, [limit]).fetchall()
        ]
