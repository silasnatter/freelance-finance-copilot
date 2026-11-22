"""Measure text-to-SQL quality on a fixed test set with demo data (NFR-08)."""

import datetime as dt
import itertools
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.llm.provider import LlmProvider
from finance_copilot.llm.sql_guard import QueryResult, execute_readonly, validate_sql
from finance_copilot.llm.text_to_sql import TextToSqlError, answer_question

CENT = Decimal("0.01")


class EvalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    expected_sql: str


@dataclass(frozen=True)
class EvalItem:
    id: str
    passed: bool
    reason: str
    seconds: float


@dataclass(frozen=True)
class EvalReport:
    items: list[EvalItem]

    @property
    def correct(self) -> int:
        return sum(item.passed for item in self.items)

    @property
    def total(self) -> int:
        return len(self.items)


def load_questions(path: Path) -> list[EvalQuestion]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalQuestion.model_validate(entry) for entry in content["questions"]]


def _normalize(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return str(value)


def _sorted_column(rows: Sequence[tuple[object, ...]], index: int) -> list[object]:
    return sorted((row[index] for row in rows), key=str)


def results_match(expected: QueryResult, actual: QueryResult) -> bool:
    """Compare rows in any order. Extra columns in the answer are allowed."""
    if len(expected.rows) != len(actual.rows):
        return False
    if not expected.rows:
        return True
    wanted = [tuple(_normalize(value) for value in row) for row in expected.rows]
    found = [tuple(_normalize(value) for value in row) for row in actual.rows]
    candidates = [
        [
            actual_index
            for actual_index in range(len(found[0]))
            if _sorted_column(found, actual_index) == _sorted_column(wanted, expected_index)
        ]
        for expected_index in range(len(wanted[0]))
    ]
    target = Counter(wanted)
    for assignment in itertools.product(*candidates):
        if len(set(assignment)) != len(assignment):
            continue
        if Counter(tuple(row[index] for index in assignment) for row in found) == target:
            return True
    return False


def run_evaluation(
    questions: Sequence[EvalQuestion], provider: LlmProvider, warehouse: Path
) -> EvalReport:
    items: list[EvalItem] = []
    for question in questions:
        expected = execute_readonly(validate_sql(question.expected_sql), warehouse)
        started = time.perf_counter()
        try:
            answer = answer_question(question.question, provider, warehouse)
        except TextToSqlError:
            passed, reason = False, "no valid query"
        else:
            actual = QueryResult(answer.columns, answer.rows, answer.truncated)
            passed = results_match(expected, actual)
            reason = "correct" if passed else "wrong result"
        items.append(EvalItem(question.id, passed, reason, time.perf_counter() - started))
    return EvalReport(items)
