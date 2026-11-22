"""Ask questions about the marts. Answers come from read-only SQL (FR-12)."""

import datetime as dt
import os
from decimal import Decimal
from typing import Any

import duckdb
import streamlit as st

from finance_copilot.config import data_target, load_settings
from finance_copilot.dashboard.data import dashboard_warehouse
from finance_copilot.llm.provider import LlmConfigurationError, LlmUnavailableError, build_provider
from finance_copilot.llm.text_to_sql import Answer, TextToSqlError, answer_question

OLLAMA_HINT = "Ollama ist nicht erreichbar. Starte es mit `docker compose --profile ollama up -d`."


def display_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def show_answer(answer: Answer) -> None:
    if answer.rows:
        st.dataframe(
            [
                {
                    column: display_value(value)
                    for column, value in zip(answer.columns, row, strict=True)
                }
                for row in answer.rows
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("Die Abfrage hat keine Ergebnisse geliefert.")
    if answer.truncated:
        st.caption("Es werden nur die ersten 200 Zeilen angezeigt.")
    st.code(answer.sql, language="sql")


st.set_page_config(page_title="Finance Chat", layout="wide")
st.title("Finance Chat")

settings = load_settings()
source = "deinen echten Daten" if data_target(os.environ) == "private" else "den Demo-Daten"
st.caption(
    f"Lokal mit {settings.llm.model} auf {source}. Die Zahlen kommen direkt aus der Datenbank, "
    "das Modell sieht nur die Tabellenstruktur. Prüfe die angezeigte Abfrage."
)

history: list[tuple[str, Answer]] = st.session_state.setdefault("chat_history", [])
for past_question, past_answer in history:
    with st.chat_message("user"):
        st.write(past_question)
    with st.chat_message("assistant"):
        show_answer(past_answer)

question = st.chat_input("Zum Beispiel: Wie hoch waren meine Kosten 2026 pro Kategorie?")
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        try:
            provider = build_provider(settings, os.environ)
            with st.spinner("Erstelle Abfrage ..."):
                answer = answer_question(
                    question, provider, dashboard_warehouse(settings, os.environ)
                )
        except (LlmUnavailableError, LlmConfigurationError):
            st.error(OLLAMA_HINT)
        except TextToSqlError:
            st.warning("Dazu konnte ich keine gültige Abfrage erstellen. Formuliere es anders.")
        except duckdb.Error:
            st.error(
                "Die Auswertung fehlt oder ist gerade in Benutzung. Starte sie mit `make run`."
            )
        else:
            show_answer(answer)
            history.append((question, answer))
