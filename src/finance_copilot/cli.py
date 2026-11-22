"""Command line entry points. Output never contains financial content (RB-04)."""

import argparse
import sys
import urllib.request
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.demo_data.wise import generate_ecb_rates, generate_wise_csv
from finance_copilot.ingestion.bank_csv import ingest_bank_csv, load_bank_rows, read_bank_csv
from finance_copilot.ingestion.bank_mapping import (
    BankRowError,
    load_bank_mapping,
    load_own_names,
)
from finance_copilot.ingestion.fx import ECB_HISTORY_URL, FxRates, save_ecb_rates

BANKS_DIR = PROJECT_ROOT / "config" / "banks"


def _demo(settings: Settings) -> int:
    demo_dir = settings.paths.demo_data
    source = demo_dir / "wise-transactions.csv"
    rates_path = demo_dir / "ecb-rates.csv"
    generate_wise_csv(source)
    generate_ecb_rates(rates_path)
    mapping = load_bank_mapping(BANKS_DIR / "wise.yaml")
    warehouse = demo_dir / "warehouse.duckdb"
    count = ingest_bank_csv(source, mapping, FxRates.from_ecb_csv(rates_path), warehouse)
    print(f"Demo data ready: {count} transactions loaded.")
    return 0


def _fetch_fx(settings: Settings) -> int:
    with urllib.request.urlopen(ECB_HISTORY_URL, timeout=30) as response:  # noqa: S310
        save_ecb_rates(response.read(), settings.paths.fx_rates)
    print("ECB reference rates updated.")
    return 0


def _ingest(settings: Settings, bank: str, file: Path) -> int:
    mapping_path = BANKS_DIR / f"{bank}.yaml"
    if not mapping_path.is_file():
        print(f"No mapping found for bank '{bank}'.", file=sys.stderr)
        return 1
    if not settings.paths.fx_rates.is_file():
        print("ECB rates missing. Run: uv run python -m finance_copilot fetch-fx", file=sys.stderr)
        return 1
    if not settings.paths.own_accounts.is_file():
        print(
            "Hint: no own_accounts.yaml found, transfers to own accounts count as expenses.",
            file=sys.stderr,
        )
    rates = FxRates.from_ecb_csv(settings.paths.fx_rates)
    own_names = load_own_names(settings.paths.own_accounts)
    try:
        rows = read_bank_csv(file, load_bank_mapping(mapping_path), rates, own_names)
    except BankRowError as error:
        print(f"Import stopped, nothing was loaded: {error}", file=sys.stderr)
        return 1
    count = load_bank_rows(rows, settings.paths.warehouse)
    flows = Counter(str(row["flow"]) for row in rows)
    summary = ", ".join(f"{flow}: {flows[flow]}" for flow in sorted(flows))
    print(f"Imported {count} transactions ({summary}).")
    return 0


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finance_copilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="generate and load synthetic data")
    commands.add_parser("fetch-fx", help="download ECB reference rates")
    ingest = commands.add_parser("ingest", help="import a bank CSV export")
    ingest.add_argument("--bank", required=True)
    ingest.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)

    active = settings or load_settings()
    if args.command == "demo":
        return _demo(active)
    if args.command == "fetch-fx":
        return _fetch_fx(active)
    return _ingest(active, args.bank, args.file)
