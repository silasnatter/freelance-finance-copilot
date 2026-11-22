"""Answer questions with read-only SQL on the marts (FR-12).

The model only receives the table structure. Row values never enter a prompt,
and the numbers shown to the user come from the database, not from the model.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from finance_copilot.llm.provider import LlmProvider
from finance_copilot.llm.sql_guard import (
    ALLOWED_TABLES,
    MART_SCHEMA,
    UnsafeSqlError,
    execute_readonly,
    validate_sql,
)

MAX_ATTEMPTS = 2
SAFE_ERROR_DETAILS = (duckdb.BinderException, duckdb.CatalogException, duckdb.ParserException)
SYSTEM_PROMPT = """You write one DuckDB SELECT query that answers a question about finances.
Return only SQL. Use only the tables below, always with the schema name marts.

Meaning of the data:
- All amounts are in EUR.
- marts.mart_monthly_pnl: one row per month. revenue_eur, expenses_eur, fees_eur, profit_eur,
  tax_payments_eur. Use it for revenue, costs and profit. Total costs = expenses_eur + fees_eur.
- marts.mart_expenses_by_category: one row per year and category, with category_name and
  amount_eur. Use it for costs by category. It already includes bank fees.
- marts.mart_tax_reserve: one row per month. target_balance_eur is the expected balance of the
  savings pot in that month and is cumulative, so use the latest month and never sum it.
- marts.fct_transactions: one row per booking. Filter by flow: income, expense, tax, transfer,
  conversion, private, investment, needs_review. Business amounts are in business_amount_eur;
  expenses are negative there. Use it for questions about single vendors or bookings.
- Category names include: Software & Hosting, Hardware & Geräte, Versicherung & SVS,
  Telefon & Internet, Steuerberatung & Buchhaltung, Weiterbildung, Reisen, Werbung,
  Büro & Arbeitsplatz, Events & Veranstaltungen, Behörden & Kammern, Bankgebühren, Sonstiges.
"""


class TextToSqlError(RuntimeError):
    """No valid query could be generated for the question."""


@dataclass(frozen=True)
class Answer:
    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


def extract_sql(response: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", response, flags=re.DOTALL | re.IGNORECASE)
    return (fenced.group(1) if fenced else response).strip()


def build_schema_prompt(warehouse: Path) -> str:
    """Describe allowed tables by name and type, without reading any row."""
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        columns = connection.execute(
            """
            select table_name, column_name, data_type
            from information_schema.columns
            where table_schema = ?
            order by table_name, ordinal_position
            """,
            [MART_SCHEMA],
        ).fetchall()
    tables: dict[str, list[str]] = {}
    for table, column, data_type in columns:
        if table in ALLOWED_TABLES:
            tables.setdefault(table, []).append(f"{column} {data_type}")
    return "\n".join(
        f"{MART_SCHEMA}.{table}({', '.join(definition)})"
        for table, definition in sorted(tables.items())
    )


def _safe_error(error: Exception) -> str:
    if isinstance(error, (UnsafeSqlError, *SAFE_ERROR_DETAILS)):
        return str(error).splitlines()[0]
    return type(error).__name__


def answer_question(question: str, provider: LlmProvider, warehouse: Path) -> Answer:
    """Generate, check and run a query, with one correction attempt."""
    schema = build_schema_prompt(warehouse)
    prompt = f"Tables:\n{schema}\n\nQuestion: {question}"
    feedback = ""
    for _ in range(MAX_ATTEMPTS):
        generated = extract_sql(provider.complete(SYSTEM_PROMPT, prompt + feedback))
        try:
            sql = validate_sql(generated)
            result = execute_readonly(sql, warehouse)
        except (UnsafeSqlError, duckdb.Error) as error:
            feedback = (
                f"\n\nYour previous query failed.\nQuery: {generated}\n"
                f"Error: {_safe_error(error)}\nReturn a corrected query."
            )
            continue
        return Answer(sql, result.columns, result.rows, result.truncated)
    raise TextToSqlError("No valid query could be generated.")
