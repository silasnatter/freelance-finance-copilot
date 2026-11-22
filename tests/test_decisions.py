import csv
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from finance_copilot.cli import main
from finance_copilot.config import PROJECT_ROOT, Settings, load_settings
from finance_copilot.ingestion.bank_mapping import BankRowError, load_bank_mapping, normalize_row
from finance_copilot.ingestion.decisions import (
    Decision,
    apply_decision,
    load_decisions,
    parse_business_amount,
    save_decision,
)
from finance_copilot.ingestion.fx import FxRates
from finance_copilot.ingestion.ledger import (
    BusinessRules,
    load_ledger_mapping,
    parse_ledger_row,
)

RowFactory = Callable[..., dict[str, str]]
LEDGER = load_ledger_mapping(PROJECT_ROOT / "config" / "banks" / "raiffeisen.yaml")
WISE = load_bank_mapping(PROJECT_ROOT / "config" / "banks" / "wise.yaml")
RULES = BusinessRules(income=("Kunde GmbH",), expense=("SVS", "Mediamarkt"), mixed=("Mediamarkt",))


def line(text: str, amount: str = "-100,00", day: str = "01") -> list[str]:
    return [f"{day}.03.2026", text, f"{day}.03.2026", amount, "EUR", f"{day}.03.2026 10:00:00:000"]


def parse(
    fields: list[str], rates: FxRates, own: frozenset[str] = frozenset()
) -> dict[str, object]:
    return parse_ledger_row(fields, LEDGER, rates, own, RULES, row_number=1)


def review_row(amount: str = "-100.00") -> dict[str, object]:
    return {
        "transaction_id": "raiffeisen:abc",
        "flow": "needs_review",
        "amount_eur": Decimal(amount),
        "business_amount_eur": Decimal("0.00"),
    }


@pytest.fixture
def rates(ecb_rates_csv: Path) -> FxRates:
    return FxRates.from_ecb_csv(ecb_rates_csv)


def test_mixed_vendor_needs_review_even_if_listed_as_expense(rates: FxRates) -> None:
    result = parse(line("Zahlungsempfänger: Mediamarkt Wien"), rates)

    assert result["flow"] == "needs_review"
    assert result["business_amount_eur"] == Decimal("0.00")


def test_own_account_wins_over_mixed_vendor(rates: FxRates) -> None:
    result = parse(line("Zahlungsempfänger: Mediamarkt"), rates, frozenset({"mediamarkt"}))

    assert result["flow"] == "transfer"


@pytest.mark.parametrize(
    ("text", "amount", "business"),
    [
        ("Auftraggeber: Kunde GmbH", "500,00", "500.00"),
        ("Zahlungsempfänger: SVS", "-90,00", "-90.00"),
        ("Zahlungsempfänger: Bäckerei", "-9,00", "0.00"),
    ],
)
def test_business_amount_follows_flow(
    rates: FxRates, text: str, amount: str, business: str
) -> None:
    assert parse(line(text, amount), rates)["business_amount_eur"] == Decimal(business)


@pytest.mark.parametrize(
    ("direction", "own", "business"),
    [("OUT", frozenset(), "-50.00"), ("OUT", frozenset({"hosting gmbh"}), "0.00")],
)
def test_wise_rows_have_business_amount(
    wise_row: RowFactory, rates: FxRates, direction: str, own: frozenset[str], business: str
) -> None:
    result = normalize_row(wise_row(Direction=direction), WISE, rates, own)

    assert result is not None
    assert result["business_amount_eur"] == Decimal(business)


def test_wise_conversion_has_no_business_amount(wise_row: RowFactory, rates: FxRates) -> None:
    result = normalize_row(wise_row(Direction="NEUTRAL"), WISE, rates)

    assert result is not None
    assert result["business_amount_eur"] == Decimal("0.00")


def test_full_business_decision_counts_whole_amount() -> None:
    row = apply_decision(review_row(), {"raiffeisen:abc": Decision(decision="business")})

    assert row["flow"] == "expense"
    assert row["business_amount_eur"] == Decimal("-100.00")


def test_partial_decision_counts_only_that_share() -> None:
    decision = Decision(decision="business", business_amount_eur=Decimal("30.50"))

    row = apply_decision(review_row(), {"raiffeisen:abc": decision})

    assert row["flow"] == "expense"
    assert row["amount_eur"] == Decimal("-100.00")
    assert row["business_amount_eur"] == Decimal("-30.50")


def test_partial_refund_keeps_positive_sign() -> None:
    decision = Decision(decision="business", business_amount_eur=Decimal("10.00"))

    row = apply_decision(review_row("25.00"), {"raiffeisen:abc": decision})

    assert row["business_amount_eur"] == Decimal("10.00")


def test_private_decision_counts_nothing() -> None:
    row = apply_decision(review_row(), {"raiffeisen:abc": Decision(decision="private")})

    assert row["flow"] == "private"
    assert row["business_amount_eur"] == Decimal("0.00")


def test_decision_is_ignored_for_rows_not_in_review() -> None:
    row = review_row() | {"flow": "transfer"}

    result = apply_decision(row, {"raiffeisen:abc": Decision(decision="business")})

    assert result["flow"] == "transfer"
    assert result["business_amount_eur"] == Decimal("0.00")


def test_row_without_decision_stays_open() -> None:
    assert apply_decision(review_row(), {})["flow"] == "needs_review"


def test_decision_above_booking_amount_is_rejected() -> None:
    decision = Decision(decision="business", business_amount_eur=Decimal("100.01"))

    with pytest.raises(BankRowError) as error:
        apply_decision(review_row(), {"raiffeisen:abc": decision})

    assert "100" not in str(error.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("89,90", "89.90"),
        ("89.90", "89.90"),
        ("1.234,56", "1234.56"),
        ("100", "100.00"),
        (" 5,5 ", "5.50"),
    ],
)
def test_business_amount_input_is_parsed(raw: str, expected: str) -> None:
    assert parse_business_amount(raw, Decimal("-2000.00")) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "2000,01", "1,2,3", "NaN", "1,234"])
def test_invalid_business_amount_input_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_business_amount(raw, Decimal("-2000.00"))


def test_decisions_round_trip_and_keep_existing_entries(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "decisions.yaml"

    save_decision(path, "bank:a", Decision(decision="private"))
    save_decision(
        path, "bank:b", Decision(decision="business", business_amount_eur=Decimal("12.30"))
    )

    assert load_decisions(path) == {
        "bank:a": Decision(decision="private"),
        "bank:b": Decision(decision="business", business_amount_eur=Decimal("12.30")),
    }


def test_missing_decisions_file_is_empty(tmp_path: Path) -> None:
    assert load_decisions(tmp_path / "missing.yaml") == {}


class FakeStdin:
    def isatty(self) -> bool:
        return True


@pytest.fixture
def settings(tmp_path: Path, ecb_rates_csv: Path) -> Settings:
    loaded = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    loaded.paths.fx_rates.parent.mkdir(parents=True)
    loaded.paths.fx_rates.write_bytes(ecb_rates_csv.read_bytes())
    loaded.paths.business_rules.parent.mkdir(parents=True, exist_ok=True)
    loaded.paths.business_rules.write_text("mixed: [Mediamarkt]\n", encoding="utf-8")
    return loaded


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "bank.csv"
    rows = [
        line("Zahlungsempfänger: Mediamarkt Wien", "-100,00", "01"),
        line("Zahlungsempfänger: Mediamarkt Graz", "-50,00", "02"),
        line("Zahlungsempfänger: Mediamarkt Linz", "-20,00", "03"),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file, delimiter=";").writerows(rows)
    return path


def stored(settings: Settings) -> list[tuple[str, Decimal]]:
    with duckdb.connect(str(settings.paths.warehouse), read_only=True) as connection:
        rows = connection.execute(
            "select flow, business_amount_eur from raw.bank_transactions order by booking_date"
        ).fetchall()
    return [(flow, Decimal(amount)) for flow, amount in rows]


def answer(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    pending = iter(answers)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(pending)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def test_decide_records_answers_and_survives_reimport(
    settings: Settings, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = ["ingest", "--bank", "raiffeisen", "--file", str(source)]
    assert main(ingest, settings) == 0
    answer(monkeypatch, ["g", "t", "abc", "30,50", "s"])

    assert main(["decide"], settings) == 0

    expected = [
        ("expense", Decimal("-100")),
        ("expense", Decimal("-30.5")),
        ("needs_review", Decimal("0")),
    ]
    assert stored(settings) == expected
    assert main(ingest, settings) == 0
    assert stored(settings) == expected


def test_decide_only_asks_for_open_bookings(
    settings: Settings, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    answer(monkeypatch, ["p", "p", "p"])
    main(["decide"], settings)
    answer(monkeypatch, [])

    assert main(["decide"], settings) == 0

    assert [flow for flow, _ in stored(settings)] == ["private", "private", "private"]


def test_decide_can_be_quit_and_resumed(
    settings: Settings, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    answer(monkeypatch, ["p", "q"])

    assert main(["decide"], settings) == 0

    assert [flow for flow, _ in stored(settings)] == ["private", "needs_review", "needs_review"]


def test_decide_refuses_output_that_is_not_a_terminal(
    settings: Settings, source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings)
    capsys.readouterr()

    assert main(["decide"], settings) == 1

    captured = capsys.readouterr()
    assert "Mediamarkt" not in captured.out + captured.err


def test_ingest_stops_on_invalid_decisions_file(
    settings: Settings, source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.paths.booking_decisions.write_text("decisions: [broken\n", encoding="utf-8")

    assert main(["ingest", "--bank", "raiffeisen", "--file", str(source)], settings) == 1

    assert "booking_decisions.yaml" in capsys.readouterr().err
