from pathlib import Path

import pytest

from finance_copilot.devtools.check_iban import find_ibans, is_valid_iban, main

# Public specification example, split so the hook does not flag this file.
EXAMPLE_IBAN = "DE89" + "3704" + "0044" + "0532" + "0130" + "00"
SPACED_IBAN = " ".join(EXAMPLE_IBAN[i : i + 4] for i in range(0, len(EXAMPLE_IBAN), 4))


def test_valid_iban_is_recognized() -> None:
    assert is_valid_iban(EXAMPLE_IBAN)


@pytest.mark.parametrize(
    "value",
    [EXAMPLE_IBAN[:-1] + "1", EXAMPLE_IBAN[:-1], "XX" + EXAMPLE_IBAN[2:], EXAMPLE_IBAN[:-1] + "-"],
)
def test_invalid_iban_is_rejected(value: str) -> None:
    assert not is_valid_iban(value)


@pytest.mark.parametrize("value", [EXAMPLE_IBAN, SPACED_IBAN])
def test_find_ibans_masks_value(value: str) -> None:
    assert list(find_ibans(f"first line\nIBAN: {value} END")) == [(2, "DE89...00")]


def test_find_ibans_ignores_ordinary_text() -> None:
    assert list(find_ibans("INVOICE AB12 is due on 2026-11-22")) == []


def test_main_fails_without_printing_full_iban(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "leak.csv"
    file.write_text(EXAMPLE_IBAN, encoding="utf-8")

    assert main([str(file)]) == 1
    output = capsys.readouterr().out
    assert "DE89...00" in output
    assert EXAMPLE_IBAN not in output


def test_main_passes_clean_and_binary_files(tmp_path: Path) -> None:
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing here", encoding="utf-8")
    binary = tmp_path / "file.bin"
    binary.write_bytes(b"\xff\xfe\x00")

    assert main([str(clean), str(binary)]) == 0
