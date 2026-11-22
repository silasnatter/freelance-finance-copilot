"""Streamlit dashboard for income, costs, profit and the tax reserve (FR-10)."""

import os

import streamlit as st

from finance_copilot.config import load_settings
from finance_copilot.dashboard.charts import profit_chart, revenue_cost_chart, top_expenses_chart
from finance_copilot.dashboard.data import (
    DashboardUnavailableError,
    available_years,
    dashboard_warehouse,
    format_eur,
    load_monthly,
    load_summary,
    load_top_expenses,
)

st.set_page_config(page_title="Finance Copilot", layout="wide")
st.title("Finance Copilot")

warehouse = dashboard_warehouse(load_settings(), os.environ)
try:
    years = available_years(warehouse)
    if not years:
        raise DashboardUnavailableError("no data")
except DashboardUnavailableError:
    st.info("Noch keine Auswertung gefunden. Starte sie mit `make run`.")
    st.stop()

year = st.selectbox("Jahr", years)
summary = load_summary(warehouse, year)
months = load_monthly(warehouse, year)
expenses = load_top_expenses(warehouse, year)
dark = st.context.theme.type == "dark"

revenue, costs, profit, reserve = st.columns(4)
revenue.metric("Umsatz", format_eur(summary.revenue_eur))
costs.metric("Kosten", format_eur(summary.costs_eur))
profit.metric("Gewinn", format_eur(summary.profit_eur))
reserve.metric("Soll auf Scalable", format_eur(summary.target_balance_eur))

st.caption(
    f"Soll auf Scalable nach deiner Regel von {summary.income_share * 100:.0f} % der Einnahmen: "
    f"Start {format_eur(summary.start_balance_eur)} "
    f"+ Anteil {format_eur(summary.reserve_added_eur)} "
    f"− Versicherung {format_eur(summary.insurance_paid_eur)} "
    f"− Steuern {format_eur(summary.tax_paid_eur)}. "
    "Vergleiche den Wert mit deinem echten Guthaben. Zinsen sind nicht enthalten. "
    "Keine Steuerberatung."
)
if summary.open_review_bookings:
    st.warning(
        f"{summary.open_review_bookings} Buchungen sind noch nicht entschieden "
        "und fehlen in den Kosten."
    )

st.subheader("Umsatz und Kosten je Monat")
st.altair_chart(revenue_cost_chart(months, dark), width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("Gewinn je Monat")
    st.altair_chart(profit_chart(months, dark), width="stretch")
with right:
    st.subheader("Größte Kosten nach Empfänger")
    if expenses:
        st.altair_chart(top_expenses_chart(expenses, dark), width="stretch")
    else:
        st.caption("Keine Kosten in diesem Jahr.")

with st.expander("Monatswerte als Tabelle"):
    st.dataframe(
        [
            {
                "Monat": row.year_month,
                "Umsatz": format_eur(row.revenue_eur),
                "Kosten": format_eur(row.costs_eur),
                "Gewinn": format_eur(row.profit_eur),
            }
            for row in months
        ],
        hide_index=True,
        width="stretch",
    )

st.caption("Offene Rechnungen folgen, sobald Ausgangsrechnungen importiert werden.")
