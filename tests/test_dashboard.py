from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from finance_copilot.config import PROJECT_ROOT, load_settings
from finance_copilot.dashboard.charts import monthly_long, profit_chart, revenue_cost_chart
from finance_copilot.dashboard.data import (
    DashboardUnavailableError,
    available_years,
    dashboard_warehouse,
    load_expenses_by_category,
    load_monthly,
    load_summary,
    load_top_expenses,
)

APP = PROJECT_ROOT / "app" / "dashboard.py"


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema marts")
        connection.execute(
            """
            create table marts.mart_monthly_pnl as select * from (values
              (date '2025-12-01', 2025, '2025-12', 100.00, 10.00, 1.00, 89.00, 0.00, 0),
              (date '2026-01-01', 2026, '2026-01', 1000.00, 200.00, 10.00, 790.00, 50.00, 2),
              (date '2026-02-01', 2026, '2026-02', 0.00, 30.00, 0.00, -30.00, 100.00, 1)
            ) as t(month_start, year, year_month, revenue_eur, expenses_eur, fees_eur,
                   profit_eur, tax_payments_eur, open_review_bookings)
            """
        )
        connection.execute(
            """
            create table marts.mart_tax_reserve as select * from (values
              (date '2025-12-01', 2025, '2025-12', 500.00, 0.50, 50.00, 0.00, 0.00, 550.00, true),
              (date '2026-01-01', 2026, '2026-01', 500.00, 0.50, 550.00, 100.00, 50.00,
               900.00, true),
              (date '2026-02-01', 2026, '2026-02', 500.00, 0.50, 550.00, 130.00, 150.00,
               770.00, true)
            ) as t(month_start, year, year_month, start_balance_eur, income_share,
                   reserve_added_eur, insurance_paid_eur, tax_paid_eur, target_balance_eur,
                   is_estimate)
            """
        )
        connection.execute(
            """
            create table marts.mart_expenses_by_category as select * from (values
              (2026, 'software', 'Software & Hosting', 1, 150.00, 3),
              (2026, 'bank_fees', 'Bankgebühren', 10, 10.00, 1),
              (2026, 'uncategorized', 'Nicht zugeordnet', 12, 80.00, 2),
              (2025, 'software', 'Software & Hosting', 1, 11.00, 1)
            ) as t(year, category_id, category_name, sort_order, amount_eur, bookings)
            """
        )
        connection.execute(
            """
            create table marts.fct_transactions as select * from (values
              ('a', date '2026-01-02', 'expense', 'Hosting', '', -100.00, 0.00),
              ('b', date '2026-01-03', 'expense', 'Hosting', '', -50.00, 0.00),
              ('c', date '2026-01-04', 'expense', 'Hosting', '', 20.00, 0.00),
              ('d', date '2026-01-05', 'expense', 'Software', '', -40.00, 0.00),
              ('e', date '2026-01-06', 'expense', 'Telefon', '', -30.00, 0.00),
              ('f', date '2026-01-07', 'expense', '', 'POS Karte', -5.00, 0.00),
              ('g', date '2026-01-08', 'private', 'Supermarkt', '', 0.00, 0.00),
              ('h', date '2026-01-09', 'income', 'Kunde', '', 1000.00, 10.00),
              ('i', date '2025-12-09', 'expense', 'Altjahr', '', -10.00, 1.00)
            ) as t(transaction_id, booking_date, flow, counterparty, reference,
                   business_amount_eur, business_fee_eur)
            """
        )
    return path


def test_years_are_newest_first(warehouse: Path) -> None:
    assert available_years(warehouse) == [2026, 2025]


def test_summary_totals_one_year_and_uses_latest_scalable_target(warehouse: Path) -> None:
    summary = load_summary(warehouse, 2026)

    assert summary.revenue_eur == Decimal("1000.00")
    assert summary.costs_eur == Decimal("240.00")
    assert summary.profit_eur == Decimal("760.00")
    assert summary.start_balance_eur == Decimal("500.00")
    assert summary.income_share == Decimal("0.50")
    assert summary.reserve_added_eur == Decimal("550.00")
    assert summary.insurance_paid_eur == Decimal("130.00")
    assert summary.tax_paid_eur == Decimal("150.00")
    assert summary.target_balance_eur == Decimal("770.00")
    assert summary.open_review_bookings == 3


def test_monthly_rows_belong_to_the_year_in_order(warehouse: Path) -> None:
    rows = load_monthly(warehouse, 2026)

    assert [row.year_month for row in rows] == ["2026-01", "2026-02"]
    assert rows[0].costs_eur == Decimal("210.00")
    assert rows[1].profit_eur == Decimal("-30.00")


def test_top_expenses_net_refunds_add_fees_and_fold_the_tail(warehouse: Path) -> None:
    rows = load_top_expenses(warehouse, 2026, limit=2)

    assert rows == [
        ("Hosting", Decimal("130.00")),
        ("Software", Decimal("40.00")),
        ("Sonstige", Decimal("45.00")),
    ]


def test_top_expenses_without_tail_have_no_other_row(warehouse: Path) -> None:
    rows = load_top_expenses(warehouse, 2025, limit=5)

    assert rows == [("Altjahr", Decimal("10.00")), ("Bankgebühren", Decimal("1.00"))]


def test_expenses_by_category_are_ranked_for_one_year(warehouse: Path) -> None:
    assert load_expenses_by_category(warehouse, 2026) == [
        ("Software & Hosting", Decimal("150.00")),
        ("Nicht zugeordnet", Decimal("80.00")),
        ("Bankgebühren", Decimal("10.00")),
    ]


def test_missing_warehouse_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DashboardUnavailableError):
        available_years(tmp_path / "missing.duckdb")
    assert not (tmp_path / "missing.duckdb").exists()


def test_missing_marts_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()

    with pytest.raises(DashboardUnavailableError):
        load_summary(path, 2026)


def test_dashboard_uses_demo_unless_private_is_requested(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )

    assert dashboard_warehouse(settings, {}) == settings.paths.demo_data / "warehouse.duckdb"
    assert dashboard_warehouse(settings, {"FINANCE_COPILOT_DATA": "private"}) == (
        settings.paths.warehouse
    )
    with pytest.raises(ValueError):
        dashboard_warehouse(settings, {"FINANCE_COPILOT_DATA": "other"})


def test_monthly_long_has_one_row_per_month_and_measure(warehouse: Path) -> None:
    rows = monthly_long(load_monthly(warehouse, 2026))

    assert {"monat": "2026-01", "art": "Kosten", "betrag": 210.0} in rows
    assert {"monat": "2026-02", "art": "Umsatz", "betrag": 0.0} in rows
    assert len(rows) == 4


def test_charts_use_a_single_y_scale_and_tooltips(warehouse: Path) -> None:
    months = load_monthly(warehouse, 2026)

    for chart in (revenue_cost_chart(months, dark=False), profit_chart(months, dark=True)):
        spec = chart.to_dict()
        assert "layer" not in spec
        assert spec["encoding"]["tooltip"]


def run_app(path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("FINANCE_COPILOT_DASHBOARD_WAREHOUSE", str(path))
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_app_shows_kpis_and_explains_scalable_target(
    warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = run_app(warehouse, monkeypatch)

    assert not app.exception
    labels = {metric.label: metric.value for metric in app.metric}
    assert labels["Umsatz"] == "1.000,00 €"
    assert labels["Gewinn"] == "760,00 €"
    assert labels["Soll auf Scalable"] == "770,00 €"
    page_text = " ".join(item.value for item in [*app.caption, *app.warning])
    assert "50 %" in page_text
    assert "Keine Steuerberatung" in page_text
    assert "3 " in " ".join(item.value for item in app.warning)


def test_app_warns_about_uncategorized_costs(
    warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = run_app(warehouse, monkeypatch)

    assert any("80,00 €" in item.value for item in app.warning)
    assert any(item.value == "Kosten nach Kategorie" for item in app.subheader)


def test_app_explains_missing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = run_app(tmp_path / "missing.duckdb", monkeypatch)

    assert not app.exception
    assert "make run" in app.info[0].value
