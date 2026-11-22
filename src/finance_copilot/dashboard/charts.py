"""Altair charts for the dashboard. Each chart has one value axis."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import altair as alt

from finance_copilot.dashboard.data import MonthRow

REVENUE = "Umsatz"
COSTS = "Kosten"
COLORS = {
    False: {REVENUE: "#2a78d6", COSTS: "#eb6834", "profit": "#1baf7a"},
    True: {REVENUE: "#3987e5", COSTS: "#d95926", "profit": "#199e70"},
}
ALL_COMMAS = "regexp(',', 'g')"
EUR_TEXT = (
    f"replace(replace(replace(format(datum.betrag, ',.2f'), {ALL_COMMAS}, '_'), '.', ','),"
    " regexp('_', 'g'), '.') + ' €'"
)
AXIS_LABEL = f"replace(format(datum.value, ',.0f'), {ALL_COMMAS}, '.')"


def monthly_long(months: Sequence[MonthRow]) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for month in months:
        rows.append({"monat": month.year_month, "art": REVENUE, "betrag": float(month.revenue_eur)})
        rows.append({"monat": month.year_month, "art": COSTS, "betrag": float(month.costs_eur)})
    return rows


def _source(values: Sequence[dict[str, str | float]]) -> Any:
    return alt.Data(values=list(values))  # type: ignore[no-untyped-call]


def _value_axis() -> alt.Axis:
    return alt.Axis(title="EUR", labelExpr=AXIS_LABEL, gridOpacity=0.25, domain=False, ticks=False)


def _month_axis() -> alt.Axis:
    return alt.Axis(title=None, labelAngle=-45, ticks=False)


def revenue_cost_chart(months: Sequence[MonthRow], dark: bool) -> alt.Chart:
    colors = COLORS[dark]
    chart: alt.Chart = (
        alt.Chart(_source(monthly_long(months)))
        .transform_calculate(betrag_text=EUR_TEXT)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("monat:N", axis=_month_axis()),
            xOffset=alt.XOffset("art:N", sort=[REVENUE, COSTS]),
            y=alt.Y("betrag:Q", axis=_value_axis()),
            color=alt.Color(
                "art:N",
                scale=alt.Scale(domain=[REVENUE, COSTS], range=[colors[REVENUE], colors[COSTS]]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("monat:N", title="Monat"),
                alt.Tooltip("art:N", title="Art"),
                alt.Tooltip("betrag_text:N", title="Betrag"),
            ],
        )
        .properties(height=300)
    )
    return chart


def profit_chart(months: Sequence[MonthRow], dark: bool) -> alt.Chart:
    values: list[dict[str, str | float]] = [
        {"monat": row.year_month, "betrag": float(row.profit_eur)} for row in months
    ]
    chart: alt.Chart = (
        alt.Chart(_source(values))
        .transform_calculate(betrag_text=EUR_TEXT)
        .mark_bar(cornerRadiusEnd=4, color=COLORS[dark]["profit"])
        .encode(
            x=alt.X("monat:N", axis=_month_axis()),
            y=alt.Y("betrag:Q", axis=_value_axis()),
            tooltip=[
                alt.Tooltip("monat:N", title="Monat"),
                alt.Tooltip("betrag_text:N", title="Gewinn"),
            ],
        )
        .properties(height=240)
    )
    return chart


def top_expenses_chart(
    rows: Sequence[tuple[str, Decimal]], dark: bool, label: str = "Kategorie"
) -> alt.Chart:
    values: list[dict[str, str | float]] = [
        {"name": name, "betrag": float(amount)} for name, amount in rows
    ]
    order = [name for name, _ in rows]
    chart: alt.Chart = (
        alt.Chart(_source(values))
        .transform_calculate(betrag_text=EUR_TEXT)
        .mark_bar(cornerRadiusEnd=4, color=COLORS[dark][COSTS])
        .encode(
            y=alt.Y(
                "name:N",
                sort=order,
                axis=alt.Axis(title=None, ticks=False, labelLimit=220, labelOverlap=False),
            ),
            x=alt.X("betrag:Q", axis=_value_axis()),
            tooltip=[
                alt.Tooltip("name:N", title=label),
                alt.Tooltip("betrag_text:N", title="Kosten"),
            ],
        )
        .properties(height=max(204, 38 * len(values)))
    )
    return chart
