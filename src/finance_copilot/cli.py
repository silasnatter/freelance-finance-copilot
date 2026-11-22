"""Command line entry points (RB-04).

Output contains no financial content. The only exception is `review`, which
refuses to run unless its output goes to a real terminal.
"""

import argparse
import sys
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.demo_data.wise import generate_ecb_rates, generate_wise_csv
from finance_copilot.ingestion.bank_csv import ingest_bank_csv, load_bank_rows, read_bank_csv
from finance_copilot.ingestion.bank_mapping import (
    BankRowError,
    load_bank_mapping,
    load_own_names,
)
from finance_copilot.ingestion.fx import ECB_HISTORY_URL, FxRates, save_ecb_rates
from finance_copilot.ingestion.ledger import (
    is_ledger_mapping,
    load_business_rules,
    load_ledger_mapping,
    read_ledger_csv,
    top_private_counterparties,
)

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


class PrivateConfigError(ValueError):
    """A private config file is invalid. The message never contains its content."""


def _load_private[T](loader: Callable[[Path], T], path: Path) -> T:
    try:
        return loader(path)
    except (yaml.YAMLError, ValidationError, AttributeError, TypeError):
        raise PrivateConfigError(f"{path.name} is invalid, check its format.") from None


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
    try:
        own_names = _load_private(load_own_names, settings.paths.own_accounts)
        if is_ledger_mapping(mapping_path):
            if not settings.paths.business_rules.is_file():
                print("Hint: no business_rules.yaml found, all rows stay private.", file=sys.stderr)
            rules = _load_private(load_business_rules, settings.paths.business_rules)
            ledger = load_ledger_mapping(mapping_path)
            rows = read_ledger_csv(file, ledger, rates, own_names, rules)
        else:
            rows = read_bank_csv(file, load_bank_mapping(mapping_path), rates, own_names)
    except (BankRowError, PrivateConfigError) as error:
        print(f"Import stopped, nothing was loaded: {error}", file=sys.stderr)
        return 1
    count = load_bank_rows(rows, settings.paths.warehouse)
    flows = Counter(str(row["flow"]) for row in rows)
    summary = ", ".join(f"{flow}: {flows[flow]}" for flow in sorted(flows))
    print(f"Imported {count} transactions ({summary}).")
    return 0


def _review(settings: Settings, limit: int) -> int:
    """Show private counterparties, only in a real terminal so names stay out of logs and chats."""
    if not sys.stdout.isatty():
        print("Review shows personal data. Run it in a separate terminal.", file=sys.stderr)
        return 1
    if not settings.paths.warehouse.is_file():
        print("No warehouse found. Import a bank export first.", file=sys.stderr)
        return 1
    for name, count in top_private_counterparties(settings.paths.warehouse, limit):
        print(f"{count:4d}  {name}")
    return 0


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finance_copilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="generate and load synthetic data")
    commands.add_parser("fetch-fx", help="download ECB reference rates")
    ingest = commands.add_parser("ingest", help="import a bank CSV export")
    ingest.add_argument("--bank", required=True)
    ingest.add_argument("--file", required=True, type=Path)
    review = commands.add_parser("review", help="list unassigned private counterparties")
    review.add_argument("--top", type=int, default=40)
    args = parser.parse_args(argv)

    active = settings or load_settings()
    if args.command == "demo":
        return _demo(active)
    if args.command == "fetch-fx":
        return _fetch_fx(active)
    if args.command == "review":
        return _review(active, args.top)
    return _ingest(active, args.bank, args.file)
