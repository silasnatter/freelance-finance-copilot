from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from finance_copilot.config import PROJECT_ROOT
from finance_copilot.llm.evaluation import (
    EvalQuestion,
    load_questions,
    results_match,
    run_evaluation,
)
from finance_copilot.llm.provider import LlmUnavailableError
from finance_copilot.llm.sql_guard import QueryResult, execute_readonly, validate_sql


def result(columns: list[str], rows: list[tuple[object, ...]]) -> QueryResult:
    return QueryResult(columns, rows, truncated=False)


class MappingProvider:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def complete(self, system: str, prompt: str) -> str:
        question = prompt.rsplit("Question: ", 1)[1].split("\n", 1)[0]
        return self.answers[question]


class BrokenProvider:
    def complete(self, system: str, prompt: str) -> str:
        raise LlmUnavailableError("down")


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema marts")
        connection.execute(
            "create table marts.mart_monthly_pnl as select * from (values "
            "('2026-01', cast(10.00 as decimal(18, 2))), ('2026-02', cast(20.00 as decimal(18, 2)))"
            ") as t(year_month, revenue_eur)"
        )
    return path


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (result(["a"], [(1,)]), result(["b"], [(1,)])),
        (result(["a"], [(Decimal("10.00"),)]), result(["a"], [(10.001,)])),
        (result(["a", "b"], [(1, "x"), (2, "y")]), result(["b", "a"], [("y", 2), ("x", 1)])),
        (result(["a"], [(5,)]), result(["year", "a"], [(2026, 5)])),
        (result(["a"], [(date(2026, 1, 1),)]), result(["a"], [("2026-01-01",)])),
        (result(["a"], [(None,)]), result(["a"], [(None,)])),
    ],
)
def test_equivalent_results_match(expected: QueryResult, actual: QueryResult) -> None:
    assert results_match(expected, actual)


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (result(["a"], [(1,)]), result(["a"], [(2,)])),
        (result(["a"], [(1,)]), result(["a"], [(1,), (1,)])),
        (result(["a", "b"], [(1, 2)]), result(["a"], [(1,)])),
        (result(["a", "b"], [(1, "x"), (2, "y")]), result(["a", "b"], [(1, "y"), (2, "x")])),
        (result(["a"], [(1,)]), result(["a"], [])),
        (result(["a"], [(10.0,)]), result(["a"], [(10.02,)])),
    ],
)
def test_different_results_do_not_match(expected: QueryResult, actual: QueryResult) -> None:
    assert not results_match(expected, actual)


def test_repository_has_twenty_valid_questions() -> None:
    questions = load_questions(PROJECT_ROOT / "evals" / "text_to_sql.yaml")

    assert len(questions) == 20
    assert len({question.id for question in questions}) == 20
    for question in questions:
        validate_sql(question.expected_sql)


def test_expected_queries_return_rows_on_demo_data(tmp_path: Path) -> None:
    from finance_copilot.config import load_settings
    from finance_copilot.orchestration.pipeline import run_pipeline

    settings = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    assert run_pipeline("demo", settings)
    warehouse = settings.paths.demo_data / "warehouse.duckdb"

    for question in load_questions(PROJECT_ROOT / "evals" / "text_to_sql.yaml"):
        rows = execute_readonly(validate_sql(question.expected_sql), warehouse).rows
        assert rows, question.id
        assert all(value is not None for value in rows[0]), question.id


def test_evaluation_counts_correct_wrong_and_failed_answers(warehouse: Path) -> None:
    questions = [
        EvalQuestion(
            id="right",
            question="Summe?",
            expected_sql="select sum(revenue_eur) from marts.mart_monthly_pnl",
        ),
        EvalQuestion(
            id="wrong",
            question="Maximum?",
            expected_sql="select max(revenue_eur) from marts.mart_monthly_pnl",
        ),
        EvalQuestion(
            id="invalid",
            question="Lösche?",
            expected_sql="select count(*) from marts.mart_monthly_pnl",
        ),
    ]
    provider = MappingProvider(
        {
            "Summe?": "select sum(revenue_eur) as total from marts.mart_monthly_pnl",
            "Maximum?": "select min(revenue_eur) from marts.mart_monthly_pnl",
            "Lösche?": "drop table marts.mart_monthly_pnl",
        }
    )

    report = run_evaluation(questions, provider, warehouse)

    assert report.correct == 1
    assert report.total == 3
    assert [item.id for item in report.items if item.passed] == ["right"]
    assert {item.id: item.reason for item in report.items}["invalid"] == "no valid query"
    assert {item.id: item.reason for item in report.items}["wrong"] == "wrong result"


def test_unavailable_model_stops_the_evaluation(warehouse: Path) -> None:
    question = EvalQuestion(
        id="q", question="Summe?", expected_sql="select 1 from marts.mart_monthly_pnl"
    )

    with pytest.raises(LlmUnavailableError):
        run_evaluation([question], BrokenProvider(), warehouse)
