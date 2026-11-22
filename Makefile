.PHONY: setup demo run run-private dagster dagster-private eval lint typecheck test dbt dbt-private check

DBT_ARGS = --project-dir dbt --profiles-dir dbt

setup:
	uv sync
	uv run pre-commit install

demo:
	uv run python -m finance_copilot demo

run:
	uv run python -m finance_copilot run

run-private:
	uv run python -m finance_copilot run --private

dagster:
	uv run python -m finance_copilot orchestrator

dagster-private:
	uv run python -m finance_copilot orchestrator --private

eval:
	uv run python -m finance_copilot eval-sql

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

dbt: demo
	uv run dbt build $(DBT_ARGS) --target demo

dbt-private:
	uv run dbt build $(DBT_ARGS) --target private

check: lint typecheck test dbt
