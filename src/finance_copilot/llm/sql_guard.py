"""Allow only read queries on the marts and run them on a locked connection (NFR-04)."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MART_SCHEMA = "marts"
ALLOWED_TABLES = frozenset(
    {
        "dim_category",
        "dim_date",
        "fct_transactions",
        "mart_costs_by_vendor",
        "mart_expenses_by_category",
        "mart_monthly_pnl",
        "mart_tax_reserve",
    }
)
SAFE_UNTYPED_FUNCTIONS = frozenset(
    {"date_part", "datepart", "day", "month", "quarter", "strftime", "week", "year"}
)
BLOCKED_FUNCTION_PREFIXES = (
    "copy",
    "current_setting",
    "duckdb_",
    "getenv",
    "glob",
    "load",
    "pragma",
    "query",
    "read",
    "scan",
    "sniff",
    "which_secret",
)
FORBIDDEN_NODES = (
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Into,
    exp.Merge,
    exp.Set,
    exp.Update,
)


class UnsafeSqlError(ValueError):
    """A query is not allowed. The message never repeats the query."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


def _check_function(node: exp.Func) -> None:
    if isinstance(node, exp.Anonymous):
        if str(node.name).casefold() not in SAFE_UNTYPED_FUNCTIONS:
            raise UnsafeSqlError("Function is not allowed.")
        return
    name = node.sql_name().casefold()
    if name.startswith(BLOCKED_FUNCTION_PREFIXES):
        raise UnsafeSqlError("Function is not allowed.")


def _check_table(table: exp.Table, cte_names: set[str]) -> None:
    if not isinstance(table.this, exp.Identifier) or table.catalog:
        raise UnsafeSqlError("Only tables in the marts schema are allowed.")
    name = table.name.casefold()
    schema = table.db.casefold()
    if not schema and name in cte_names:
        return
    if schema not in ("", MART_SCHEMA) or name not in ALLOWED_TABLES:
        raise UnsafeSqlError("Only tables in the marts schema are allowed.")
    table.set("db", exp.to_identifier(MART_SCHEMA))


def validate_sql(sql: str) -> str:
    """Return a normalized query, or raise if it is anything but a read on the marts."""
    try:
        statements = [
            statement for statement in sqlglot.parse(sql, read="duckdb") if statement is not None
        ]
    except SqlglotError:
        raise UnsafeSqlError("Query cannot be parsed.") from None
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise UnsafeSqlError("Exactly one SELECT statement is allowed.")

    statement = statements[0]
    if any(isinstance(node, FORBIDDEN_NODES) for node in statement.walk()):
        raise UnsafeSqlError("Only read queries are allowed.")
    for function in statement.find_all(exp.Func):
        _check_function(function)
    cte_names = {cte.alias.casefold() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        _check_table(table, cte_names)
    return statement.sql(dialect="duckdb")


def execute_readonly(
    sql: str, warehouse: Path, max_rows: int = 200, timeout_seconds: float = 10
) -> QueryResult:
    """Run a query without write or file access, limited in rows and time."""
    with duckdb.connect(
        str(warehouse), read_only=True, config={"enable_external_access": "false"}
    ) as connection:
        connection.execute("set lock_configuration = true")
        timer = threading.Timer(timeout_seconds, connection.interrupt)
        timer.start()
        try:
            cursor = connection.execute(sql)
            columns = [column[0] for column in cursor.description or []]
            rows = cursor.fetchmany(max_rows + 1)
        finally:
            timer.cancel()
    return QueryResult(columns, rows[:max_rows], len(rows) > max_rows)
