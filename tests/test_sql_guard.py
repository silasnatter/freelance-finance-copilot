from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from finance_copilot.llm.sql_guard import UnsafeSqlError, execute_readonly, validate_sql


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema marts")
        connection.execute("create schema raw")
        connection.execute(
            "create table marts.mart_monthly_pnl as "
            "select i as month, cast(i * 10 as decimal(18, 2)) as revenue_eur "
            "from range(1, 6) as t(i)"
        )
        connection.execute("create table raw.bank_transactions as select 'secret' as reference")
    return path


@pytest.mark.parametrize(
    "sql",
    [
        "select * from marts.mart_monthly_pnl",
        "SELECT year, SUM(revenue_eur) FROM marts.mart_monthly_pnl GROUP BY 1 ORDER BY 2 DESC",
        "with x as (select year, sum(revenue_eur) as r from marts.mart_monthly_pnl group by 1) "
        "select * from x",
        "select c.category_name, sum(t.business_amount_eur) from marts.fct_transactions t "
        "join marts.dim_category c on t.category_id = c.category_id group by 1",
        "select strftime(booking_date, '%Y-%m'), count(*) from marts.fct_transactions group by 1",
        "select extract(year from booking_date), abs(amount_eur), round(amount_eur, 2), "
        "coalesce(reference, ''), lower(counterparty) from marts.fct_transactions",
    ],
)
def test_read_queries_on_marts_are_allowed(sql: str) -> None:
    assert validate_sql(sql)


def test_unqualified_mart_is_qualified() -> None:
    assert "marts.mart_monthly_pnl" in validate_sql("select * from mart_monthly_pnl")


def test_trailing_semicolon_is_allowed() -> None:
    assert validate_sql("select * from marts.mart_monthly_pnl;")


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "not sql at all (",
        "drop table marts.mart_monthly_pnl",
        "delete from marts.mart_monthly_pnl",
        "update marts.mart_monthly_pnl set revenue_eur = 0",
        "insert into marts.mart_monthly_pnl values (1, 2)",
        "create table marts.x as select 1",
        "alter table marts.mart_monthly_pnl add column x int",
        "attach 'other.duckdb' as other",
        "copy marts.mart_monthly_pnl to 'leak.csv'",
        "pragma database_list",
        "set enable_external_access = true",
        "install httpfs",
        "load httpfs",
        "select 1; drop table marts.mart_monthly_pnl",
        "select * from marts.mart_monthly_pnl; select * from marts.mart_monthly_pnl",
        "select * from raw.bank_transactions",
        "select * from bank_transactions",
        "select * from information_schema.tables",
        "select * from main.mart_monthly_pnl",
        "select * from other.marts.mart_monthly_pnl",
        "select * from duckdb_settings()",
        "select * from read_csv('data/private/x.csv')",
        "select * from read_parquet('x.parquet')",
        "select * from 'data/private/x.csv'",
        'select * from "data/private/x.csv"',
        "select * from glob('data/private/*')",
        "select read_text('data/private/own_accounts.yaml')",
        "select getenv('HOME')",
        "select current_setting('threads')",
        "select * from query('select * from raw.bank_transactions')",
        "select * from query_table('raw.bank_transactions')",
        "select (select reference from raw.bank_transactions limit 1)",
        "with mart_monthly_pnl as (select * from raw.bank_transactions) "
        "select * from mart_monthly_pnl",
        "select * from marts.mart_monthly_pnl union all select * from raw.bank_transactions",
    ],
)
def test_everything_else_is_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        validate_sql(sql)


def test_error_does_not_echo_the_query() -> None:
    with pytest.raises(UnsafeSqlError) as error:
        validate_sql("select 'Secret Name' from raw.bank_transactions")

    assert "Secret Name" not in str(error.value)


def test_execute_returns_columns_and_rows(warehouse: Path) -> None:
    result = execute_readonly(
        validate_sql("select month, revenue_eur from marts.mart_monthly_pnl order by 1"),
        warehouse,
    )

    assert result.columns == ["month", "revenue_eur"]
    assert result.rows[0] == (1, Decimal("10.00"))
    assert result.truncated is False


def test_execute_limits_rows(warehouse: Path) -> None:
    result = execute_readonly(
        validate_sql("select month from marts.mart_monthly_pnl order by 1"),
        warehouse,
        max_rows=2,
    )

    assert result.rows == [(1,), (2,)]
    assert result.truncated is True


def test_connection_cannot_write_even_without_the_guard(warehouse: Path) -> None:
    with pytest.raises(duckdb.Error):
        execute_readonly("delete from marts.mart_monthly_pnl", warehouse)

    with duckdb.connect(str(warehouse), read_only=True) as connection:
        assert connection.execute("select count(*) from marts.mart_monthly_pnl").fetchone() == (5,)


def test_connection_cannot_read_files_even_without_the_guard(
    warehouse: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")

    with pytest.raises(duckdb.Error):
        execute_readonly(f"select * from read_csv('{secret}')", warehouse)  # noqa: S608


def test_slow_query_is_interrupted(warehouse: Path) -> None:
    with pytest.raises(duckdb.Error):
        execute_readonly(
            "select count(*) from range(100000000000) a, range(100000000000) b",
            warehouse,
            timeout_seconds=0.2,
        )
