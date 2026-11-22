import csv
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_csv import load_bank_rows
from finance_copilot.ingestion.bank_mapping import BankRowError
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import (
    BusinessRules,
    load_business_rules,
    load_ledger_mapping,
    parse_ledger_row,
    read_ledger_csv,
    top_private_counterparties,
)

MAPPING = load_ledger_mapping(PROJECT_ROOT / "config" / "banks" / "raiffeisen.yaml")
RULES = BusinessRules(income=("Kunde GmbH",), expense=("SVS", "Hetzner"), tax=("Finanzamt",))
OWN = frozenset({"demo freelancer"})


def line(
    text: str = "Zahlungsempfänger: Bäckerei Huber Verwendungszweck: Brot",
    amount: str = "-1.234,56",
    booking: str = "15.03.2026",
    stamp: str = "16.03.2026 10:20:30:123",
) -> list[str]:
    return [booking, text, "17.03.2026", amount, "EUR", stamp]


@pytest.fixture
def rates(ecb_rates_csv: Path) -> FxRates:
    return FxRates.from_ecb_csv(ecb_rates_csv)


def parse(fields: list[str], rates: FxRates) -> dict[str, object]:
    return parse_ledger_row(fields, MAPPING, rates, OWN, RULES, row_number=1)


def write_ledger(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file, delimiter=";").writerows(rows)
    return path


def test_outgoing_row_is_parsed(rates: FxRates) -> None:
    result = parse(line(), rates)

    assert result["counterparty"] == "Bäckerei Huber"
    assert result["reference"] == "Brot"
    assert result["amount_eur"] == Decimal("-1234.56")
    assert result["amount_original"] == Decimal("-1234.56")
    assert result["currency_original"] == "EUR"
    assert result["booking_date"] == date(2026, 3, 15)
    assert result["booked_at"] == datetime(2026, 3, 16, 10, 20, 30, 123000)
    assert result["fee_eur"] == Decimal("0.00")
    assert str(result["transaction_id"]).startswith("raiffeisen:")


def test_incoming_row_uses_payer(rates: FxRates) -> None:
    text = "Auftraggeberreferenz: R-1 Auftraggeber: Kunde GmbH Zahlungsreferenz: Rechnung 7"

    result = parse(line(text=text, amount="500,00"), rates)

    assert result["counterparty"] == "Kunde GmbH"
    assert result["reference"] == "Rechnung 7"


def test_recipient_id_label_does_not_become_counterparty(rates: FxRates) -> None:
    result = parse(line(text="Empfänger-Kennung: AT12ZZZ Empfänger: Shop KG Mandat: M-1"), rates)

    assert result["counterparty"] == "Shop KG"


def test_unmatched_row_is_private(rates: FxRates) -> None:
    assert parse(line(), rates)["flow"] == "private"


@pytest.mark.parametrize(
    ("text", "amount", "flow"),
    [
        ("Auftraggeber: KUNDE gmbh", "500,00", "income"),
        ("Zahlungsempfänger: SVS", "-900,00", "expense"),
        ("Zahlungsempfänger: Finanzamt Österreich", "-2.000,00", "tax"),
        ("Auftraggeber: Finanzamt Österreich", "100,00", "tax"),
        ("Auftraggeber: Hetzner", "5,00", "expense"),
    ],
)
def test_rules_classify_business_rows(rates: FxRates, text: str, amount: str, flow: str) -> None:
    assert parse(line(text=text, amount=amount), rates)["flow"] == flow


def test_rule_matches_whole_words_only(rates: FxRates) -> None:
    assert parse(line(text="Zahlungsempfänger: SVSHOP Wien"), rates)["flow"] == "private"


def test_refund_keeps_its_positive_sign(rates: FxRates) -> None:
    result = parse(line(text="Auftraggeber: Hetzner", amount="5,00"), rates)

    assert result["amount_eur"] == Decimal("5.00")


def test_own_account_wins_over_rules(rates: FxRates) -> None:
    rules = BusinessRules(income=("Demo Freelancer",))

    result = parse_ledger_row(
        line(text="Auftraggeber: Demo  FREELANCER", amount="10,00"),
        MAPPING,
        rates,
        OWN,
        rules,
        row_number=1,
    )

    assert result["flow"] == "transfer"


def test_card_payment_without_label_matches_on_text(rates: FxRates) -> None:
    result = parse(line(text="POS 12,00 HETZNER ONLINE 14.03."), rates)

    assert result["counterparty"] == ""
    assert result["reference"] == "POS 12,00 HETZNER ONLINE 14.03."
    assert result["flow"] == "expense"


def test_transaction_id_is_stable_and_content_based(rates: FxRates) -> None:
    first = parse(line(), rates)["transaction_id"]

    assert parse(line(), rates)["transaction_id"] == first
    assert parse(line(amount="-1,00"), rates)["transaction_id"] != first


def test_identical_rows_in_one_file_stay_distinct(tmp_path: Path, rates: FxRates) -> None:
    path = write_ledger(tmp_path / "bank.csv", [line(), line()])

    rows = read_ledger_csv(path, MAPPING, rates, OWN, RULES)

    assert len({row["transaction_id"] for row in rows}) == 2


@pytest.mark.parametrize(
    "fields",
    [
        line(amount="12.34"),
        line(amount="abc"),
        line(booking="2026-03-15"),
        line(stamp="gestern"),
        line()[:5],
    ],
)
def test_malformed_row_error_has_no_content(rates: FxRates, fields: list[str]) -> None:
    with pytest.raises(BankRowError) as error:
        parse(fields, rates)

    assert "row 1" in str(error.value)
    assert "Bäckerei" not in str(error.value)


def test_repeated_import_creates_no_duplicates(tmp_path: Path, rates: FxRates) -> None:
    path = write_ledger(tmp_path / "bank.csv", [line(), line(amount="-2,00")])
    warehouse = tmp_path / "warehouse.duckdb"

    load_bank_rows(read_ledger_csv(path, MAPPING, rates, OWN, RULES), warehouse)
    load_bank_rows(read_ledger_csv(path, MAPPING, rates, OWN, RULES), warehouse)

    with duckdb.connect(str(warehouse), read_only=True) as connection:
        count = connection.execute("select count(*) from raw.bank_transactions").fetchone()
    assert count == (2,)


def test_business_rules_file_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("income: [A]\nexpense:\ntax: [B]\n", encoding="utf-8")

    assert load_business_rules(path) == BusinessRules(income=("A",), expense=(), tax=("B",))


def test_missing_business_rules_mean_everything_is_private(tmp_path: Path) -> None:
    assert load_business_rules(tmp_path / "missing.yaml") == BusinessRules()


def test_top_private_counterparties_groups_and_falls_back_to_text(
    tmp_path: Path, rates: FxRates
) -> None:
    path = write_ledger(
        tmp_path / "bank.csv",
        [
            line(),
            line(amount="-2,00"),
            line(text="POS KARTE SHOP"),
            line(text="Zahlungsempfänger: SVS", amount="-9,00"),
        ],
    )
    warehouse = tmp_path / "warehouse.duckdb"
    load_bank_rows(read_ledger_csv(path, MAPPING, rates, OWN, RULES), warehouse)

    assert top_private_counterparties(warehouse, 10) == [
        ("Bäckerei Huber", 2),
        ("POS KARTE SHOP", 1),
    ]


@pytest.fixture
def settings(tmp_path: Path, ecb_rates_csv: Path) -> Settings:
    loaded = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    loaded.paths.fx_rates.parent.mkdir(parents=True)
    loaded.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    return loaded


def test_cli_imports_ledger_with_rules_and_prints_counts_only(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.business_rules.parent.mkdir(parents=True)
    settings.paths.business_rules.write_text("expense: [SVS]\n", encoding="utf-8")
    source = write_ledger(
        tmp_path / "bank.csv", [line(), line(text="Zahlungsempfänger: SVS", amount="-9,00")]
    )

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 0

    output = capsys.readouterr().out
    assert "expense: 1" in output
    assert "private: 1" in output
    assert "Bäckerei" not in output


def test_review_refuses_output_that_is_not_a_terminal(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_ledger(tmp_path / "bank.csv", [line()])
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    capsys.readouterr()

    assert main(["review"], settings) == 1

    captured = capsys.readouterr()
    assert "Bäckerei" not in captured.out + captured.err


def test_review_lists_names_in_a_terminal(
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_ledger(tmp_path / "bank.csv", [line()])
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    capsys.readouterr()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert main(["review"], settings) == 0

    assert "Bäckerei Huber" in capsys.readouterr().out


def test_invalid_rules_file_fails_without_echoing_names(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.business_rules.parent.mkdir(parents=True)
    settings.paths.business_rules.write_text("unknown: [Secret Customer]\n", encoding="utf-8")
    source = write_ledger(tmp_path / "bank.csv", [line()])

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 1

    captured = capsys.readouterr()
    assert "business_rules.yaml" in captured.err
    assert "Secret Customer" not in captured.out + captured.err
    assert not settings.paths.warehouse.exists()


def test_broken_yaml_in_own_accounts_fails_without_echoing_names(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.own_accounts.parent.mkdir(parents=True)
    settings.paths.own_accounts.write_text("names: [Secret Name\n", encoding="utf-8")
    source = write_ledger(tmp_path / "bank.csv", [line()])

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 1

    captured = capsys.readouterr()
    assert "own_accounts.yaml" in captured.err
    assert "Secret Name" not in captured.out + captured.err
