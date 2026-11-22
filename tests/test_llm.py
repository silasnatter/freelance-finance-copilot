import json
import threading
from collections.abc import Iterator
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from finance_copilot.config import PROJECT_ROOT, load_settings
from finance_copilot.llm.provider import (
    LlmConfigurationError,
    LlmUnavailableError,
    OllamaProvider,
    build_provider,
)
from finance_copilot.llm.text_to_sql import (
    TextToSqlError,
    answer_question,
    build_schema_prompt,
    extract_sql,
)

CHAT_PAGE = PROJECT_ROOT / "app" / "pages" / "1_Chat.py"


class ScriptedProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self.responses.pop(0)


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema marts")
        connection.execute("create schema raw")
        connection.execute(
            "create table marts.mart_monthly_pnl as select 2026 as year, "
            "cast(100.00 as decimal(18, 2)) as revenue_eur"
        )
        connection.execute(
            "create table marts.fct_transactions as select 'a' as transaction_id, "
            "'Secret Vendor' as counterparty, cast(-5 as decimal(18, 2)) as amount_eur, "
            "cast(-2 as decimal(18, 2)) as business_amount_eur"
        )
        connection.execute("create table raw.bank_transactions as select 'hidden' as reference")
    return path


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("select 1", "select 1"),
        ("```sql\nselect 1;\n```", "select 1;"),
        ("Hier ist die Abfrage:\n```\nselect 1\n```\nDanke", "select 1"),
        ("  SELECT 1  ", "SELECT 1"),
    ],
)
def test_extract_sql(response: str, expected: str) -> None:
    assert extract_sql(response) == expected


def test_schema_prompt_has_structure_but_no_data(warehouse: Path) -> None:
    prompt = build_schema_prompt(warehouse)

    assert "marts.mart_monthly_pnl" in prompt
    assert "revenue_eur" in prompt
    assert "Secret Vendor" not in prompt
    assert "bank_transactions" not in prompt


def test_schema_prompt_hides_full_booking_amounts(warehouse: Path) -> None:
    prompt = build_schema_prompt(warehouse)

    assert "business_amount_eur" in prompt
    assert " amount_eur" not in prompt


def test_answer_runs_generated_sql(warehouse: Path) -> None:
    provider = ScriptedProvider("```sql\nselect year, revenue_eur from mart_monthly_pnl\n```")

    answer = answer_question("Wie hoch war der Umsatz?", provider, warehouse)

    assert "marts.mart_monthly_pnl" in answer.sql
    assert answer.columns == ["year", "revenue_eur"]
    assert answer.rows == [(2026, Decimal("100.00"))]
    assert "Wie hoch war der Umsatz?" in provider.calls[0][1]


def test_prompt_never_contains_row_values(warehouse: Path) -> None:
    provider = ScriptedProvider("select counterparty from marts.fct_transactions")

    answer_question("Wer?", provider, warehouse)

    assert all("Secret Vendor" not in system + prompt for system, prompt in provider.calls)


def test_unsafe_sql_gets_one_retry(warehouse: Path) -> None:
    provider = ScriptedProvider(
        "select * from raw.bank_transactions", "select revenue_eur from marts.mart_monthly_pnl"
    )

    answer = answer_question("Umsatz?", provider, warehouse)

    assert answer.rows == [(Decimal("100.00"),)]
    assert len(provider.calls) == 2


def test_failed_execution_gets_one_retry(warehouse: Path) -> None:
    provider = ScriptedProvider(
        "select missing from marts.mart_monthly_pnl",
        "select revenue_eur from marts.mart_monthly_pnl",
    )

    answer = answer_question("Umsatz?", provider, warehouse)

    assert answer.rows == [(Decimal("100.00"),)]
    assert "missing" in provider.calls[1][1]


def test_gives_up_after_retry_and_never_runs_unsafe_sql(warehouse: Path) -> None:
    provider = ScriptedProvider(
        "drop table marts.mart_monthly_pnl", "delete from marts.mart_monthly_pnl"
    )

    with pytest.raises(TextToSqlError):
        answer_question("Lösche alles", provider, warehouse)

    with duckdb.connect(str(warehouse), read_only=True) as connection:
        assert connection.execute("select count(*) from marts.mart_monthly_pnl").fetchone() == (1,)


class OllamaStub(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    reply = "select revenue_eur from marts.mart_monthly_pnl"

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        OllamaStub.requests.append(json.loads(self.rfile.read(length)))
        body = json.dumps({"message": {"role": "assistant", "content": self.reply}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: Any) -> None:
        return


@pytest.fixture
def ollama() -> Iterator[str]:
    OllamaStub.requests = []
    server = HTTPServer(("127.0.0.1", 0), OllamaStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_ollama_provider_sends_a_deterministic_chat_request(ollama: str) -> None:
    provider = OllamaProvider(ollama, "test-model")

    assert provider.complete("System", "Frage") == OllamaStub.reply

    request = OllamaStub.requests[0]
    assert request["model"] == "test-model"
    assert request["stream"] is False
    assert request["options"]["temperature"] == 0
    assert request["messages"] == [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Frage"},
    ]


def test_unreachable_ollama_is_reported() -> None:
    provider = OllamaProvider("http://127.0.0.1:9", "test-model", timeout_seconds=1)

    with pytest.raises(LlmUnavailableError):
        provider.complete("System", "Frage")


@pytest.mark.parametrize(
    "url",
    ["https://example.com", "http://192.168.1.5:11434", "http://localhost.example.com:11434"],
)
def test_remote_llm_is_refused_without_opt_in(url: str) -> None:
    with pytest.raises(LlmConfigurationError):
        OllamaProvider(url, "test-model")


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434"])
def test_local_llm_is_accepted(url: str) -> None:
    assert OllamaProvider(url, "test-model")


def test_provider_uses_settings_and_environment(tmp_path: Path, ollama: str) -> None:
    settings = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )

    provider = build_provider(settings, {"FINANCE_COPILOT_LLM_URL": ollama})

    assert provider.complete("System", "Frage") == OllamaStub.reply
    assert OllamaStub.requests[0]["model"] == settings.llm.model


def test_claude_provider_is_refused_until_implemented(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=PROJECT_ROOT / "config" / "settings.yaml", project_root=tmp_path, env={}
    )
    claude = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"provider": "claude"})}
    )

    with pytest.raises(LlmConfigurationError):
        build_provider(claude, {})


def run_chat(path: Path, url: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("FINANCE_COPILOT_DASHBOARD_WAREHOUSE", str(path))
    monkeypatch.setenv("FINANCE_COPILOT_LLM_URL", url)
    return AppTest.from_file(str(CHAT_PAGE), default_timeout=30).run()


def test_chat_shows_sql_and_result(
    warehouse: Path, ollama: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = run_chat(warehouse, ollama, monkeypatch)

    app.chat_input[0].set_value("Wie hoch war der Umsatz?").run()

    assert not app.exception
    assert any("marts.mart_monthly_pnl" in block.value for block in app.code)
    assert len(app.dataframe) == 1


def test_chat_explains_when_ollama_is_missing(
    warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = run_chat(warehouse, "http://127.0.0.1:9", monkeypatch)

    app.chat_input[0].set_value("Wie hoch war der Umsatz?").run()

    assert not app.exception
    assert any("Ollama" in item.value for item in app.error)
