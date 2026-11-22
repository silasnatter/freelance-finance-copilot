import csv
from collections.abc import Callable
from pathlib import Path

import pytest

WISE_COLUMNS = [
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
]


def build_wise_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(WISE_COLUMNS, "")
    row.update(
        {
            "ID": "TRANSFER-1",
            "Status": "COMPLETED",
            "Direction": "OUT",
            "Created on": "2026-03-02 09:00:00",
            "Finished on": "2026-03-02 10:00:00",
            "Source fee amount": "0",
            "Source fee currency": "EUR",
            "Source name": "Demo Freelancer",
            "Source amount (after fees)": "50.00",
            "Source currency": "EUR",
            "Target name": "Hosting GmbH",
            "Target amount (after fees)": "50.00",
            "Target currency": "EUR",
            "Exchange rate": "1",
            "Reference": "Server March",
        }
    )
    row.update(overrides)
    return row


@pytest.fixture
def wise_row() -> Callable[..., dict[str, str]]:
    return build_wise_row


@pytest.fixture
def write_wise_csv(tmp_path: Path) -> Callable[..., Path]:
    def write(rows: list[dict[str, str]], name: str = "wise.csv") -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=WISE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    return write


@pytest.fixture
def ecb_rates_csv(tmp_path: Path) -> Path:
    path = tmp_path / "ecb.csv"
    path.write_text(
        "Date,USD,CHF,\n2026-03-03,1.10,0.5,\n2026-03-02,1.10,0.8,\n2026-02-27,1.10,N/A,\n"
        "2026-02-20,1.10,0.9,\n",
        encoding="utf-8",
    )
    return path
