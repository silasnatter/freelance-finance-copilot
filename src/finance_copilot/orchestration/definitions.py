"""Entry point for the Dagster UI. Uses demo data unless private data is requested."""

import os

from finance_copilot.config import data_target, load_settings
from finance_copilot.orchestration.pipeline import build_definitions

defs = build_definitions(data_target(os.environ), load_settings())
