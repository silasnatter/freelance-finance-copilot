"""Deterministic synthetic data in the Wise export format (FR-01)."""

import csv
import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker

WISE_COLUMNS = (
    "ID",
    "Status",
    "Direction",
    "Created on",
    "Finished on",
    "Source fee amount",
    "Source fee currency",
    "Target fee amount",
    "Target fee currency",
    "Source name",
    "Source amount (after fees)",
    "Source currency",
    "Target name",
    "Target amount (after fees)",
    "Target currency",
    "Exchange rate",
    "Reference",
    "Batch",
    "Created by",
    "Category",
    "Note",
)
OWNER = "Demo Freelancer"
VENDORS = (
    ("Nordcloud Hosting GmbH", "Server", 18, 45),
    ("Codewerk Software GmbH", "Lizenz", 12, 60),
    ("Coworking Mitte GmbH", "Arbeitsplatz", 180, 260),
    ("Funknetz Telekom AG", "Mobilfunk", 25, 40),
    ("Sicher Versicherung AG", "Berufshaftpflicht", 30, 55),
)


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _timestamp(rng: random.Random, year: int, month: int) -> datetime:
    return datetime(
        year, month, rng.randint(1, 28), rng.randint(7, 19), rng.randint(0, 59), rng.randint(0, 59)
    )


def _row(
    rng: random.Random,
    when: datetime,
    direction: str,
    source: tuple[str, Decimal, str],
    target: tuple[str, Decimal, str],
    fee: tuple[str, Decimal, str],
    reference: str,
) -> dict[str, str]:
    side, fee_amount, fee_currency = fee
    created = when - timedelta(minutes=rng.randint(1, 240))
    source_rate = target[1] / source[1]
    row = dict.fromkeys(WISE_COLUMNS, "")
    row.update(
        {
            "Status": "COMPLETED",
            "Direction": direction,
            "Created on": created.strftime("%Y-%m-%d %H:%M:%S"),
            "Finished on": when.strftime("%Y-%m-%d %H:%M:%S"),
            f"{side} fee amount": str(fee_amount),
            f"{side} fee currency": fee_currency,
            "Source name": source[0],
            "Source amount (after fees)": str(source[1]),
            "Source currency": source[2],
            "Target name": target[0],
            "Target amount (after fees)": str(target[1]),
            "Target currency": target[2],
            "Exchange rate": str(source_rate.quantize(Decimal("0.0001"))),
            "Reference": reference,
            "Created by": OWNER,
        }
    )
    return row


def _month_rows(
    rng: random.Random, customers: list[str], year: int, month: int
) -> list[dict[str, str]]:
    rows = []
    received = Decimal("0")
    for number in range(rng.randint(1, 2)):
        amount = _money(rng.uniform(3000, 9000))
        fee = _money(rng.uniform(1, 6))
        received += amount
        customer = rng.choice(customers)
        reference = f"Rechnung {year}-{month:02d}{number + 1:02d}"
        when = _timestamp(rng, year, month)
        rows.append(
            _row(
                rng,
                when,
                "IN",
                (customer, amount + fee, "CHF"),
                (OWNER, amount, "CHF"),
                ("Target", fee, "CHF"),
                reference,
            )
        )

    source = _money(received * Decimal("0.7"))
    fee = _money(source * Decimal("0.005"))
    rate = Decimal(str(round(rng.uniform(1.04, 1.1), 4)))
    rows.append(
        _row(
            rng,
            _timestamp(rng, year, month),
            "NEUTRAL",
            (OWNER, source, "CHF"),
            (OWNER, _money(source * rate), "EUR"),
            ("Source", fee, "CHF"),
            "Currency exchange",
        )
    )

    for vendor, label, low, high in rng.sample(VENDORS, k=rng.randint(3, len(VENDORS))):
        amount = _money(rng.uniform(low, high))
        from_chf = rng.random() < 0.15
        source_currency = "CHF" if from_chf else "EUR"
        source_amount = _money(amount / Decimal("1.07")) if from_chf else amount
        fee_amount = _money(rng.uniform(0.2, 1.2)) if from_chf else Decimal("0.00")
        rows.append(
            _row(
                rng,
                _timestamp(rng, year, month),
                "OUT",
                (OWNER, source_amount, source_currency),
                (vendor, amount, "EUR"),
                ("Source", fee_amount, source_currency),
                f"{label} {year}-{month:02d}",
            )
        )
    return rows


def generate_wise_csv(path: Path, seed: int = 42, year: int = 2026) -> None:
    """Write twelve months of synthetic transactions."""
    rng = random.Random(seed)  # noqa: S311
    fake = Faker("de_DE")
    fake.seed_instance(seed)
    customers = [fake.unique.company() for _ in range(3)]

    rows = [row for month in range(1, 13) for row in _month_rows(rng, customers, year, month)]
    rows.sort(key=lambda row: row["Finished on"])
    for number, row in enumerate(rows, start=1):
        row["ID"] = f"DEMO-{year}-{number:05d}"

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=WISE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_ecb_rates(path: Path, seed: int = 42, year: int = 2026) -> None:
    """Write synthetic weekday CHF quotes in the ECB history layout."""
    rng = random.Random(seed)  # noqa: S311
    rate = 0.94
    lines = []
    day = date(year, 1, 1)
    while day.year == year:
        if day.weekday() < 5:
            rate = min(0.99, max(0.89, rate + rng.uniform(-0.003, 0.003)))
            lines.append(f"{day.isoformat()},{rate:.4f},")
        day += timedelta(days=1)

    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(["Date,CHF,", *reversed(lines)]) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")
