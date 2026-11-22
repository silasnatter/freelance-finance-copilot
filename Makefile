.PHONY: setup demo run lint typecheck test dbt check

DBT_ARGS = --project-dir dbt --profiles-dir dbt

setup:
	uv sync
	uv run pre-commit install

demo:
	@echo "make demo is implemented in M1 (FR-01)."

run:
	@echo "make run is implemented in M3 (FR-10)."

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

dbt:
	uv run dbt build $(DBT_ARGS)

check: lint typecheck test dbt
