import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

from finance_copilot.config import PROJECT_ROOT
from finance_copilot.demo_data.wise import generate_ecb_rates, generate_wise_csv
from finance_copilot.devtools.check_iban import find_ibans
from finance_copilot.ingestion.bank_csv import ingest_bank_csv
from finance_copilot.ingestion.bank_mapping import load_bank_mapping
from finance_copilot.ingestion.fx import FxRates

from .conftest import WISE_COLUMNS


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_same_seed_produces_identical_files(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"

    generate_wise_csv(first, seed=7)
    generate_wise_csv(second, seed=7)

    assert first.read_bytes() == second.read_bytes()


def test_different_seed_changes_data(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"

    generate_wise_csv(first, seed=7)
    generate_wise_csv(second, seed=8)

    assert first.read_bytes() != second.read_bytes()


def test_demo_csv_matches_real_wise_header(tmp_path: Path) -> None:
    path = tmp_path / "wise.csv"

    generate_wise_csv(path, seed=7)

    with path.open(encoding="utf-8", newline="") as file:
        assert next(csv.reader(file)) == WISE_COLUMNS


def test_demo_covers_twelve_months_and_all_flows(tmp_path: Path) -> None:
    path = tmp_path / "wise.csv"

    generate_wise_csv(path, seed=7, year=2026)

    rows = read_rows(path)
    assert {row["Finished on"][:7] for row in rows} == {f"2026-{m:02d}" for m in range(1, 13)}
    directions = Counter(row["Direction"] for row in rows)
    assert directions["IN"] >= 12
    assert directions["NEUTRAL"] >= 12
    assert directions["OUT"] >= 12
    assert len({row["ID"] for row in rows}) == len(rows)


def test_demo_income_is_chf_and_conversions_stay_on_own_account(tmp_path: Path) -> None:
    path = tmp_path / "wise.csv"

    generate_wise_csv(path, seed=7)

    rows = read_rows(path)
    assert all(row["Target currency"] == "CHF" for row in rows if row["Direction"] == "IN")
    conversions = [row for row in rows if row["Direction"] == "NEUTRAL"]
    assert all(row["Source name"] == row["Target name"] for row in conversions)
    assert all(row["Source currency"] == "CHF" for row in conversions)
    assert all(row["Target currency"] == "EUR" for row in conversions)


def test_demo_contains_no_valid_iban(tmp_path: Path) -> None:
    path = tmp_path / "wise.csv"

    generate_wise_csv(path, seed=7)

    assert list(find_ibans(path.read_text(encoding="utf-8"))) == []


def test_demo_rates_cover_every_weekday_of_the_year(tmp_path: Path) -> None:
    path = tmp_path / "rates.csv"

    generate_ecb_rates(path, seed=7, year=2026)

    rows = read_rows(path)
    assert len(rows) == 261
    assert all(Decimal("0.85") <= Decimal(row["CHF"]) <= Decimal("1.05") for row in rows)


def test_generated_demo_files_import_completely(tmp_path: Path) -> None:
    source = tmp_path / "wise.csv"
    rates_path = tmp_path / "rates.csv"
    generate_wise_csv(source, seed=7)
    generate_ecb_rates(rates_path, seed=7)
    mapping = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")

    count = ingest_bank_csv(
        source, mapping, FxRates.from_ecb_csv(rates_path), tmp_path / "warehouse.duckdb"
    )

    assert count == len(read_rows(source))
