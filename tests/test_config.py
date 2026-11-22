from pathlib import Path

import pytest
from pydantic import ValidationError

from finance_copilot.config import PROJECT_ROOT, WAREHOUSE_ENV_VAR, load_settings


def test_repository_settings_load_with_safe_defaults() -> None:
    settings = load_settings(env={})

    assert settings.paths.warehouse == PROJECT_ROOT / "data" / "warehouse.duckdb"
    assert settings.paths.private_data == PROJECT_ROOT / "data" / "private"
    assert settings.llm.provider == "ollama"
    assert settings.llm.external_llm_opt_in is False


def test_environment_overrides_warehouse(tmp_path: Path) -> None:
    target = tmp_path / "custom.duckdb"

    settings = load_settings(env={WAREHOUSE_ENV_VAR: str(target)})

    assert settings.paths.warehouse == target


def test_unknown_setting_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(
        "paths: {warehouse: a, demo_data: b, private_data: c, inbox: d}\nunknown: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_path=config, project_root=tmp_path, env={})
