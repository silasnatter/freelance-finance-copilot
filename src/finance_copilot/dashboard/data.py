"""Read-only access to the dbt marts for the dashboard (FR-10)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from finance_copilot.config import Settings, data_target

WAREHOUSE_OVERRIDE = "FINANCE_COPILOT_DASHBOARD_WAREHOUSE"
OTHER_LABEL = "Sonstige"
FEES_LABEL = "Bankgebühren"


class DashboardUnavailableError(RuntimeError):
    """The marts cannot be read, for example because they were not built yet."""


@dataclass(frozen=True)
class Summary:
    revenue_eur: Decimal
    costs_eur: Decimal
    profit_eur: Decimal
    reserve_rate: Decimal
    reserve_target_eur: Decimal
    tax_paid_eur: Decimal
    reserve_open_eur: Decimal
    open_review_bookings: int


@dataclass(frozen=True)
class MonthRow:
    year_month: str
    revenue_eur: Decimal
    costs_eur: Decimal
    profit_eur: Decimal


def dashboard_warehouse(settings: Settings, env: Mapping[str, str]) -> Path:
    """Use demo data unless private data is requested explicitly."""
    if override := env.get(WAREHOUSE_OVERRIDE):
        return Path(override)
    if data_target(env) == "private":
        return settings.paths.warehouse
    return settings.paths.demo_data / "warehouse.duckdb"


def _query(warehouse: Path, sql: str, parameters: Sequence[object] = ()) -> list[tuple[Any, ...]]:
    if not warehouse.is_file():
        raise DashboardUnavailableError("warehouse not found")
    try:
        with duckdb.connect(str(warehouse), read_only=True) as connection:
            return connection.execute(sql, list(parameters)).fetchall()
    except duckdb.Error:
        raise DashboardUnavailableError("marts cannot be read") from None


def available_years(warehouse: Path) -> list[int]:
    rows = _query(warehouse, "select distinct year from marts.mart_monthly_pnl order by 1 desc")
    return [int(row[0]) for row in rows]


def load_summary(warehouse: Path, year: int) -> Summary:
    totals = _query(
        warehouse,
        """
        select sum(revenue_eur), sum(expenses_eur + fees_eur), sum(profit_eur),
               sum(open_review_bookings)
        from marts.mart_monthly_pnl
        where year = ?
        """,
        [year],
    )[0]
    reserve = _query(
        warehouse,
        """
        select reserve_rate, reserve_target_ytd_eur, tax_paid_ytd_eur, reserve_open_eur
        from marts.mart_tax_reserve
        where year = ?
        order by month_start desc
        limit 1
        """,
        [year],
    )
    if totals[0] is None or not reserve:
        raise DashboardUnavailableError("no data for this year")
    rate, target, paid, reserve_open = reserve[0]
    return Summary(
        revenue_eur=Decimal(totals[0]),
        costs_eur=Decimal(totals[1]),
        profit_eur=Decimal(totals[2]),
        reserve_rate=Decimal(rate),
        reserve_target_eur=Decimal(target),
        tax_paid_eur=Decimal(paid),
        reserve_open_eur=Decimal(reserve_open),
        open_review_bookings=int(totals[3]),
    )


def load_monthly(warehouse: Path, year: int) -> list[MonthRow]:
    rows = _query(
        warehouse,
        """
        select year_month, revenue_eur, expenses_eur + fees_eur, profit_eur
        from marts.mart_monthly_pnl
        where year = ?
        order by month_start
        """,
        [year],
    )
    return [
        MonthRow(str(row[0]), Decimal(row[1]), Decimal(row[2]), Decimal(row[3])) for row in rows
    ]


def load_top_expenses(warehouse: Path, year: int, limit: int = 8) -> list[tuple[str, Decimal]]:
    """Largest cost positions, net of refunds, with the tail folded into one row."""
    rows = _query(
        warehouse,
        """
        with costs as (
            select coalesce(nullif(counterparty, ''), left(reference, 40)) as label,
                   -business_amount_eur as amount
            from marts.fct_transactions
            where flow = 'expense' and extract(year from booking_date) = ?
            union all
            select ? as label, business_fee_eur as amount
            from marts.fct_transactions
            where extract(year from booking_date) = ?
        )
        select label, sum(amount) as total
        from costs
        group by 1
        having sum(amount) > 0
        order by total desc, label
        """,
        [year, FEES_LABEL, year],
    )
    positions = [(str(label), Decimal(total)) for label, total in rows]
    if len(positions) <= limit:
        return positions
    tail = sum((amount for _, amount in positions[limit:]), Decimal("0.00"))
    return [*positions[:limit], (OTHER_LABEL, tail)]


def format_eur(amount: Decimal) -> str:
    text = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"
