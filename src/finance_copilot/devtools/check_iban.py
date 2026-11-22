"""Pre-commit hook that blocks files containing valid IBANs (NFR-05)."""

import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

IBAN_LENGTHS = {
    "AT": 20,
    "BE": 16,
    "CH": 21,
    "DE": 22,
    "DK": 18,
    "ES": 24,
    "FI": 18,
    "FR": 27,
    "GB": 22,
    "IE": 22,
    "IT": 27,
    "LI": 21,
    "LU": 20,
    "NL": 18,
    "NO": 15,
    "PL": 28,
    "PT": 25,
    "SE": 24,
}
CANDIDATE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}")


def is_valid_iban(value: str) -> bool:
    """Check country length and the ISO 13616 mod-97 checksum."""
    compact = value.replace(" ", "").upper()
    if IBAN_LENGTHS.get(compact[:2]) != len(compact) or not compact.isalnum():
        return False
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def find_ibans(text: str) -> Iterator[tuple[int, str]]:
    """Yield line number and masked value for each valid IBAN in the text."""
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in CANDIDATE.finditer(line):
            compact = match.group().replace(" ", "")
            length = IBAN_LENGTHS.get(compact[:2])
            if length and len(compact) >= length and is_valid_iban(compact[:length]):
                yield line_number, f"{compact[:4]}...{compact[length - 2 : length]}"


def main(argv: Sequence[str] | None = None) -> int:
    """Report findings with masked values, so the hook never prints a full IBAN."""
    paths = sys.argv[1:] if argv is None else argv
    found = False
    for name in paths:
        try:
            text = Path(name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, masked in find_ibans(text):
            print(f"{name}:{line_number}: possible IBAN {masked}")
            found = True
    return int(found)


if __name__ == "__main__":
    raise SystemExit(main())
