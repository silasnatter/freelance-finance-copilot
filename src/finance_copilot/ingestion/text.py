"""Shared name matching for account and vendor rules."""

import re
from collections.abc import Sequence


def normalize_name(value: str) -> str:
    """Make names comparable across spelling and spacing."""
    return " ".join(value.split()).casefold()


def matches_any(terms: Sequence[str], haystack: str) -> bool:
    """Return whether a term occurs as whole words in an already normalized text."""
    for term in terms:
        needle = normalize_name(term)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            return True
    return False
