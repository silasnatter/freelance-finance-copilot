"""Rule-based cost categories (FR-05). Vendor rules stay in the private folder."""

from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict

from finance_copilot.ingestion.text import matches_any, normalize_name

UNCATEGORIZED = "uncategorized"
BANK_FEES = "bank_fees"
SYSTEM_CATEGORIES = frozenset({UNCATEGORIZED, BANK_FEES})
CategoryRules = Mapping[str, tuple[str, ...]]


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str


def load_categories(path: Path) -> tuple[Category, ...]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    categories = tuple(Category.model_validate(entry) for entry in content["categories"])
    ids = [category.id for category in categories]
    if len(ids) != len(set(ids)) or not set(ids) >= SYSTEM_CATEGORIES:
        raise ValueError("Category ids must be unique and include the system categories.")
    return categories


def load_category_rules(path: Path, categories: Sequence[Category]) -> dict[str, tuple[str, ...]]:
    """Read private rules in catalog order. Errors never contain vendor names."""
    if not path.is_file():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowed = {category.id for category in categories} - SYSTEM_CATEGORIES
    if not set(content) <= allowed:
        raise ValueError("Category rules contain an invalid category.")
    rules: dict[str, tuple[str, ...]] = {}
    for category in categories:
        terms = content.get(category.id)
        if terms is None:
            continue
        if not isinstance(terms, list):
            raise ValueError("Category rules must be lists.")
        rules[category.id] = tuple(str(term) for term in terms)
    return rules


def assign_category(counterparty: str, text: str, rules: CategoryRules) -> tuple[str, str]:
    """Return the category and its source. The first category in catalog order wins."""
    haystack = normalize_name(counterparty or text)
    for category_id, terms in rules.items():
        if matches_any(terms, haystack):
            return category_id, "rule"
    return UNCATEGORIZED, "none"


def store_categories(categories: Sequence[Category], warehouse: Path) -> None:
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("create schema if not exists raw")
        connection.execute(
            "create or replace table raw.categories (id varchar, name varchar, sort_order integer)"
        )
        connection.executemany(
            "insert into raw.categories values (?, ?, ?)",
            [
                (category.id, category.name, order)
                for order, category in enumerate(categories, start=1)
            ],
        )


def uncategorized_expenses(warehouse: Path, limit: int) -> list[tuple[str, int]]:
    """Business costs without a category, to help complete the rules."""
    query = """
        select coalesce(nullif(counterparty, ''), left(reference, 40)) as name, count(*) as rows
        from raw.bank_transactions
        where flow = 'expense' and category_id = 'uncategorized'
        group by 1
        order by rows desc, name
        limit ?
    """
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        return [
            (str(name), int(rows)) for name, rows in connection.execute(query, [limit]).fetchall()
        ]
