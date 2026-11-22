"""Settings for the Scalable safety pot (FR-17)."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReserveSettings(BaseModel):
    """The pot starts with a balance and receives a share of all business income."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: dt.date
    start_balance_eur: Decimal = Field(ge=0, decimal_places=2)
    income_share: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)

    @field_validator("start_balance_eur", mode="before")
    @classmethod
    def _accept_decimal_comma(cls, value: object) -> object:
        if isinstance(value, str) and "," in value:
            return value.replace(".", "").replace(",", ".")
        return value


def load_reserve_settings(path: Path) -> ReserveSettings:
    """Read the private settings. Without a file, the pot starts empty."""
    if not path.is_file():
        return ReserveSettings(start_date=dt.date(2000, 1, 1), start_balance_eur=Decimal("0"))
    return ReserveSettings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def store_reserve_settings(settings: ReserveSettings, warehouse: Path) -> None:
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("create schema if not exists raw")
        connection.execute(
            """
            create or replace table raw.reserve_settings as
            select
                cast(? as date) as start_date,
                cast(? as decimal(18, 2)) as start_balance_eur,
                cast(? as decimal(5, 4)) as income_share
            """,
            [settings.start_date, settings.start_balance_eur, settings.income_share],
        )
