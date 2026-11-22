import csv
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_mapping import load_bank_mapping, normalize_row
from finance_copilot.ingestion.categories import (
    assign_category,
    load_categories,
    load_category_rules,
)
from finance_copilot.ingestion.decisions import Decision, apply_decision
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import (
    BusinessRules,
    load_ledger_mapping,
    parse_ledger_row,
)
from finance_copilot.ingestion.typed_export import load_typed_mapping, parse_typed_row

RowFactory = Callable[..., dict[str, str]]
CATALOG_PATH = PROJECT_ROOT / "config" / "categories.yaml"
CATALOG = load_categories(CATALOG_PATH)
LEDGER = load_ledger_mapping(PROJECT_ROOT / "config" / "banks" / "raiffeisen.yaml")
TYPED = load_typed_mapping(PROJECT_ROOT / "config" / "banks" / "trade_republic.yaml")
WISE = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")
RULES = {"software": ("Hetzner",), "hardware": ("Mediamarkt",), "insurance": ("SVS",)}
BUSINESS = BusinessRules(expense=("Hetzner", "SVS"), mixed=("Mediamarkt",))


def line(text: str, amount: str = "-100,00") -> list[str]:
    return ["01.03.2026", text, "01.03.2026", amount, "EUR", "01.03.2026 10:00:00:000"]


def typed_row(name: str, booking_type: str = "CARD_TRANSACTION") -> dict[str, str]:
    columns = [
        "fee",
        "original_amount",
        "original_currency",
        "fx_rate",
        "counterparty_name",
        "description",
        "payment_reference",
    ]
    return dict.fromkeys(columns, "") | {
        "transaction_id": "tr-1",
        "datetime": "2026-03-01T10:00:00Z",
        "date": "2026-03-01",
        "type": booking_type,
        "name": name,
        "amount": "-10.00",
        "currency": "EUR",
    }


@pytest.fixture
def rates(ecb_rates_csv: Path) -> FxRates:
    return FxRates.from_ecb_csv(ecb_rates_csv)


def test_catalog_contains_system_categories_in_order() -> None:
    ids = [category.id for category in CATALOG]

    assert ids[0] == "software"
    assert ids[-1] == "uncategorized"
    assert "bank_fees" in ids


@pytest.mark.parametrize(
    "body",
    [
        "categories:\n  - {id: a, name: A}\n  - {id: a, name: B}\n"
        "  - {id: bank_fees, name: F}\n  - {id: uncategorized, name: U}\n",
        "categories:\n  - {id: a, name: A}\n  - {id: uncategorized, name: U}\n",
        "categories:\n  - {id: a, name: A}\n  - {id: bank_fees, name: F}\n",
    ],
)
def test_invalid_catalog_is_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "categories.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError):
        load_categories(path)


def test_rules_are_loaded_in_catalog_order(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("insurance: [SVS]\nsoftware: [Hetzner, Codewerk]\nother:\n", encoding="utf-8")

    rules = load_category_rules(path, CATALOG)

    assert list(rules) == ["software", "insurance"]
    assert rules["software"] == ("Hetzner", "Codewerk")


@pytest.mark.parametrize("category", ["unknown", "uncategorized", "bank_fees"])
def test_rules_for_invalid_categories_are_rejected(tmp_path: Path, category: str) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(f"{category}: [Secret Vendor]\n", encoding="utf-8")

    with pytest.raises(ValueError) as error:
        load_category_rules(path, CATALOG)

    assert "Secret Vendor" not in str(error.value)


def test_missing_rules_file_is_empty(tmp_path: Path) -> None:
    assert load_category_rules(tmp_path / "missing.yaml", CATALOG) == {}


@pytest.mark.parametrize(
    ("counterparty", "text", "expected"),
    [
        ("HETZNER Online", "", ("software", "rule")),
        ("", "POS 12,00 hetzner 14.03.", ("software", "rule")),
        ("Bäckerei", "Hetzner im Text", ("uncategorized", "none")),
        ("Hetznerei", "", ("uncategorized", "none")),
        ("", "", ("uncategorized", "none")),
    ],
)
def test_assign_category(counterparty: str, text: str, expected: tuple[str, str]) -> None:
    assert assign_category(counterparty, text, RULES) == expected


def test_first_category_in_catalog_order_wins() -> None:
    rules = {"software": ("Shop",), "hardware": ("Shop",)}

    assert assign_category("Shop", "", rules) == ("software", "rule")


def test_ledger_row_has_category(rates: FxRates) -> None:
    row = parse_ledger_row(
        line("Zahlungsempfänger: SVS"),
        LEDGER,
        rates,
        frozenset(),
        BUSINESS,
        row_number=1,
        category_rules=RULES,
    )

    assert row["category_id"] == "insurance"
    assert row["category_source"] == "rule"


def test_card_payment_has_category(rates: FxRates) -> None:
    row = parse_typed_row(
        typed_row("Hetzner"), TYPED, rates, frozenset(), BUSINESS, category_rules=RULES
    )

    assert row["category_id"] == "software"


def test_investment_is_never_categorized(rates: FxRates) -> None:
    row = parse_typed_row(
        typed_row("Hetzner", "BUY"), TYPED, rates, frozenset(), BUSINESS, category_rules=RULES
    )

    assert row["category_id"] == "uncategorized"
    assert row["category_source"] == "none"


def test_wise_row_has_category(wise_row: RowFactory, rates: FxRates) -> None:
    row = normalize_row(wise_row(**{"Target name": "Hetzner"}), WISE, rates, category_rules=RULES)

    assert row is not None
    assert row["category_id"] == "software"


def test_decided_mixed_vendor_keeps_its_category(rates: FxRates) -> None:
    row = parse_ledger_row(
        line("Zahlungsempfänger: Mediamarkt"),
        LEDGER,
        rates,
        frozenset(),
        BUSINESS,
        row_number=1,
        category_rules=RULES,
    )

    decided = apply_decision(
        row,
        {
            str(row["transaction_id"]): Decision(
                decision="business", business_amount_eur=Decimal("40.00")
            )
        },
    )

    assert decided["flow"] == "expense"
    assert decided["category_id"] == "hardware"


@pytest.fixture
def settings(tmp_path: Path, ecb_rates_csv: Path) -> Settings:
    loaded = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    loaded.paths.fx_rates.parent.mkdir(parents=True)
    loaded.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    loaded.paths.category_rules.parent.mkdir(parents=True, exist_ok=True)
    loaded.paths.business_rules.write_text("expense: [SVS, Hetzner]\n", encoding="utf-8")
    return loaded


def write_export(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file, delimiter=";").writerows(rows)
    return path


def test_ingest_stores_categories_without_printing_rules(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.category_rules.write_text("insurance: [SVS]\n", encoding="utf-8")
    source = write_export(tmp_path / "bank.csv", [line("Zahlungsempfänger: SVS")])

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 0

    assert "SVS" not in capsys.readouterr().out
    with duckdb.connect(str(settings.paths.warehouse), read_only=True) as connection:
        assert connection.execute(
            "select category_id, category_source from raw.bank_transactions"
        ).fetchall() == [("insurance", "rule")]
        names = connection.execute(
            "select name from raw.categories where id = 'insurance'"
        ).fetchone()
    assert names == ("Versicherung & SVS",)


def test_invalid_rules_stop_import_without_echoing_names(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.category_rules.write_text("unknown: [Secret Vendor]\n", encoding="utf-8")
    source = write_export(tmp_path / "bank.csv", [line("Zahlungsempfänger: SVS")])

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 1

    captured = capsys.readouterr()
    assert "category_rules.yaml" in captured.err
    assert "Secret Vendor" not in captured.out + captured.err
    assert not settings.paths.warehouse.exists()


def test_demo_expenses_are_all_categorized(settings: Settings) -> None:
    assert main(["demo"], settings) == 0

    demo = settings.paths.demo_data / "warehouse.duckdb"
    with duckdb.connect(str(demo), read_only=True) as connection:
        missing = connection.execute(
            "select count(*) from raw.bank_transactions "
            "where flow = 'expense' and category_id = 'uncategorized'"
        ).fetchone()
    assert missing == (0,)


def test_uncategorized_review_needs_a_terminal(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_export(tmp_path / "bank.csv", [line("Zahlungsempfänger: SVS")])
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    capsys.readouterr()

    assert main(["review", "--uncategorized"], settings) == 1

    captured = capsys.readouterr()
    assert "SVS" not in captured.out + captured.err


def test_uncategorized_review_lists_only_open_business_costs(
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.paths.category_rules.write_text("insurance: [SVS]\n", encoding="utf-8")
    source = write_export(
        tmp_path / "bank.csv",
        [
            line("Zahlungsempfänger: SVS"),
            line("Zahlungsempfänger: Hetzner"),
            line("Zahlungsempfänger: Bäckerei"),
        ],
    )
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    capsys.readouterr()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert main(["review", "--uncategorized"], settings) == 0

    output = capsys.readouterr().out
    assert "Hetzner" in output
    assert "SVS" not in output
    assert "Bäckerei" not in output


def test_catalog_rejects_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "categories.yaml"
    path.write_text("categories:\n  - {id: a}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_categories(path)
