"""Command line entry points (RB-04).

Output contains no financial content. The only exceptions are `review` and
`decide`, which refuse to run unless their output goes to a real terminal.
"""

import argparse
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from finance_copilot.config import (
    DATA_ENV_VAR,
    PROJECT_ROOT,
    DataTarget,
    Settings,
    load_settings,
)
from finance_copilot.demo_data.wise import generate_ecb_rates, generate_wise_csv
from finance_copilot.ingestion.bank_csv import ingest_bank_csv, load_bank_rows, read_bank_csv
from finance_copilot.ingestion.bank_mapping import (
    BankRowError,
    load_bank_mapping,
    load_own_names,
)
from finance_copilot.ingestion.categories import (
    load_categories,
    load_category_rules,
    store_categories,
    uncategorized_expenses,
)
from finance_copilot.ingestion.decisions import (
    Decision,
    PendingBooking,
    apply_decision,
    load_decisions,
    parse_business_amount,
    pending_bookings,
    save_decision,
    store_decision,
)
from finance_copilot.ingestion.fx import ECB_HISTORY_URL, FxRates, save_ecb_rates
from finance_copilot.ingestion.ledger import (
    is_ledger_mapping,
    load_business_rules,
    load_ledger_mapping,
    read_ledger_csv,
    top_private_counterparties,
)
from finance_copilot.ingestion.reserve import load_reserve_settings, store_reserve_settings
from finance_copilot.ingestion.typed_export import (
    is_typed_mapping,
    load_typed_mapping,
    read_typed_csv,
)

BANKS_DIR = PROJECT_ROOT / "config" / "banks"
DEMO_RESERVE = PROJECT_ROOT / "config" / "reserve.demo.yaml"
DEMO_CATEGORY_RULES = PROJECT_ROOT / "config" / "category_rules.demo.yaml"
CATEGORIES = PROJECT_ROOT / "config" / "categories.yaml"
DECIDE_PROMPT = "[g] geschäftlich  [p] privat  [t] Teilbetrag  [s] später  [q] beenden > "


def _demo(settings: Settings) -> int:
    demo_dir = settings.paths.demo_data
    source = demo_dir / "wise-transactions.csv"
    rates_path = demo_dir / "ecb-rates.csv"
    generate_wise_csv(source)
    generate_ecb_rates(rates_path)
    mapping = load_bank_mapping(BANKS_DIR / "wise.yaml")
    warehouse = demo_dir / "warehouse.duckdb"
    categories = load_categories(CATEGORIES)
    category_rules = load_category_rules(DEMO_CATEGORY_RULES, categories)
    count = ingest_bank_csv(
        source, mapping, FxRates.from_ecb_csv(rates_path), warehouse, category_rules
    )
    store_reserve_settings(load_reserve_settings(DEMO_RESERVE), warehouse)
    store_categories(categories, warehouse)
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
    except (yaml.YAMLError, ValidationError, ValueError, AttributeError, TypeError):
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
        reserve = _load_private(load_reserve_settings, settings.paths.reserve)
        categories = load_categories(CATEGORIES)
        category_rules = _load_private(
            lambda path: load_category_rules(path, categories), settings.paths.category_rules
        )
        is_ledger = is_ledger_mapping(mapping_path)
        if is_ledger or is_typed_mapping(mapping_path):
            if not settings.paths.business_rules.is_file():
                print("Hint: no business_rules.yaml found, all rows stay private.", file=sys.stderr)
            rules = _load_private(load_business_rules, settings.paths.business_rules)
            decisions = _load_private(load_decisions, settings.paths.booking_decisions)
            if is_ledger:
                ledger = load_ledger_mapping(mapping_path)
                rows = read_ledger_csv(
                    file, ledger, rates, own_names, rules, decisions, category_rules
                )
            else:
                typed = load_typed_mapping(mapping_path)
                rows = read_typed_csv(
                    file, typed, rates, own_names, rules, decisions, category_rules
                )
        else:
            rows = read_bank_csv(
                file, load_bank_mapping(mapping_path), rates, own_names, category_rules
            )
    except (BankRowError, PrivateConfigError) as error:
        print(f"Import stopped, nothing was loaded: {error}", file=sys.stderr)
        return 1
    count = load_bank_rows(rows, settings.paths.warehouse)
    store_reserve_settings(reserve, settings.paths.warehouse)
    store_categories(categories, settings.paths.warehouse)
    flows = Counter(str(row["flow"]) for row in rows)
    summary = ", ".join(f"{flow}: {flows[flow]}" for flow in sorted(flows))
    print(f"Imported {count} transactions ({summary}).")
    return 0


def _review(settings: Settings, limit: int, uncategorized: bool = False) -> int:
    """Show private counterparties, only in a real terminal so names stay out of logs and chats."""
    if not sys.stdout.isatty():
        print("Review shows personal data. Run it in a separate terminal.", file=sys.stderr)
        return 1
    if not settings.paths.warehouse.is_file():
        print("No warehouse found. Import a bank export first.", file=sys.stderr)
        return 1
    load_rows = uncategorized_expenses if uncategorized else top_private_counterparties
    for name, count in load_rows(settings.paths.warehouse, limit):
        print(f"{count:4d}  {name}")
    return 0


def _format_eur(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _ask_decision(booking: PendingBooking) -> Decision | None | Literal["quit"]:
    """Ask until the answer is valid. None means the booking stays open."""
    while True:
        choice = input(DECIDE_PROMPT).strip().casefold()
        if choice == "g":
            return Decision(decision="business")
        if choice == "p":
            return Decision(decision="private")
        if choice == "s":
            return None
        if choice == "q":
            return "quit"
        if choice != "t":
            print("Bitte g, p, t, s oder q eingeben.")
            continue
        while True:
            try:
                share = parse_business_amount(
                    input("Geschäftlicher Anteil in €: "), booking.amount_eur
                )
            except ValueError:
                print(f"Bitte einen Betrag bis {_format_eur(abs(booking.amount_eur))} € eingeben.")
                continue
            return Decision(decision="business", business_amount_eur=share)


def _decide(settings: Settings) -> int:
    """Resolve open bookings, only in a real terminal so data stays out of logs and chats."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Decide shows personal data. Run it in a separate terminal.", file=sys.stderr)
        return 1
    if not settings.paths.warehouse.is_file():
        print("No warehouse found. Import a bank export first.", file=sys.stderr)
        return 1
    path = settings.paths.booking_decisions
    try:
        _load_private(load_decisions, path)
    except PrivateConfigError as error:
        print(error, file=sys.stderr)
        return 1

    bookings = pending_bookings(settings.paths.warehouse)
    decided = 0
    for position, booking in enumerate(bookings, start=1):
        print(
            f"\n({position}/{len(bookings)})  {booking.booking_date:%d.%m.%Y}   "
            f"{booking.name}   {_format_eur(booking.amount_eur)} €"
        )
        try:
            answer = _ask_decision(booking)
        except EOFError:
            break
        if answer == "quit":
            break
        if answer is None:
            continue
        save_decision(path, booking.transaction_id, answer)
        row: dict[str, object] = {
            "transaction_id": booking.transaction_id,
            "flow": "needs_review",
            "amount_eur": booking.amount_eur,
            "business_amount_eur": Decimal("0.00"),
        }
        store_decision(
            settings.paths.warehouse, apply_decision(row, {booking.transaction_id: answer})
        )
        decided += 1
    print(f"\n{decided} entschieden, {len(bookings) - decided} offen.")
    return 0


def app_command() -> list[str]:
    """Start the dashboard on this machine only and without usage statistics."""
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(PROJECT_ROOT / "app" / "dashboard.py"),
        "--server.address=127.0.0.1",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=minimal",
    ]


def orchestrator_command() -> list[str]:
    """Start the Dagster UI on this machine only."""
    return [
        sys.executable,
        "-m",
        "dagster",
        "dev",
        "-m",
        "finance_copilot.orchestration.definitions",
        "--host",
        "127.0.0.1",
    ]


def _launch(command: list[str], target: DataTarget) -> int:
    dagster_home = PROJECT_ROOT / ".dagster"
    dagster_home.mkdir(exist_ok=True)
    environment = os.environ | {
        DATA_ENV_VAR: target,
        "DAGSTER_DISABLE_TELEMETRY": "yes",
        "DAGSTER_HOME": str(dagster_home),
    }
    try:
        return subprocess.run(command, env=environment, check=False).returncode  # noqa: S603
    except KeyboardInterrupt:
        return 0


def _pipeline(settings: Settings, target: DataTarget) -> int:
    from finance_copilot.orchestration.pipeline import run_pipeline  # noqa: PLC0415

    if run_pipeline(target, settings):
        print("Pipeline finished.")
        return 0
    print("Pipeline failed.", file=sys.stderr)
    return 1


def _eval_sql(settings: Settings) -> int:
    """Run the text-to-SQL test set. It only uses synthetic demo data."""
    from finance_copilot.llm.evaluation import load_questions, run_evaluation  # noqa: PLC0415
    from finance_copilot.llm.provider import (  # noqa: PLC0415
        LlmConfigurationError,
        LlmUnavailableError,
        build_provider,
    )

    warehouse = settings.paths.demo_data / "warehouse.duckdb"
    if not warehouse.is_file():
        print("Demo data missing. Run: make run", file=sys.stderr)
        return 1
    questions = load_questions(PROJECT_ROOT / "evals" / "text_to_sql.yaml")
    try:
        report = run_evaluation(questions, build_provider(settings, os.environ), warehouse)
    except (LlmUnavailableError, LlmConfigurationError):
        print(
            "Ollama is not available. Run: docker compose --profile ollama up -d", file=sys.stderr
        )
        return 1
    for item in report.items:
        print(f"{'ok  ' if item.passed else 'FAIL'} {item.id}: {item.reason} ({item.seconds:.1f}s)")
    print(f"Correct: {report.correct}/{report.total}")
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
    review.add_argument(
        "--uncategorized", action="store_true", help="list business costs without a category"
    )
    commands.add_parser("decide", help="decide open bookings of mixed vendors")
    commands.add_parser("eval-sql", help="measure text-to-SQL on demo data")
    for name, description in (
        ("pipeline", "run imports and dbt once"),
        ("run", "run the pipeline and open the dashboard"),
        ("orchestrator", "open the Dagster UI"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("--private", action="store_true", help="use real data")
    args = parser.parse_args(argv)

    active = settings or load_settings()
    if args.command == "demo":
        return _demo(active)
    if args.command == "fetch-fx":
        return _fetch_fx(active)
    if args.command == "review":
        return _review(active, args.top, args.uncategorized)
    if args.command == "decide":
        return _decide(active)
    if args.command == "eval-sql":
        return _eval_sql(active)
    if args.command in ("pipeline", "run", "orchestrator"):
        target: DataTarget = "private" if args.private else "demo"
        if args.command == "orchestrator":
            return _launch(orchestrator_command(), target)
        result = _pipeline(active, target)
        if args.command == "pipeline" or result != 0:
            return result
        return _launch(app_command(), target)
    return _ingest(active, args.bank, args.file)
