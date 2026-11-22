"""Load project settings from config/settings.yaml and the environment (NFR-06)."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_ENV_VAR = "FINANCE_COPILOT_WAREHOUSE"


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    warehouse: Path
    demo_data: Path
    private_data: Path
    inbox: Path
    fx_rates: Path = Path("data/reference/eurofxref-hist.csv")
    own_accounts: Path = Path("data/private/own_accounts.yaml")


class LlmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["ollama", "claude"] = "ollama"
    external_llm_opt_in: bool = False


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: PathSettings
    llm: LlmSettings = LlmSettings()


def load_settings(
    config_path: Path | None = None,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read settings and resolve all configured paths against the project root."""
    environment = os.environ if env is None else env
    path = config_path or project_root / "config" / "settings.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    settings = Settings.model_validate(raw)

    values = settings.paths.model_dump()
    if warehouse := environment.get(WAREHOUSE_ENV_VAR):
        values["warehouse"] = Path(warehouse)
    resolved = PathSettings(**{key: project_root / value for key, value in values.items()})
    return settings.model_copy(update={"paths": resolved})
