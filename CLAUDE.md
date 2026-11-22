# Finance Copilot – Kontext für Claude

## Projekt
Lokale Analytics-Plattform für Freelance-Finanzen. Anforderungen: docs/requirements.md (Quelle der Wahrheit).
Backlog: TODO.md – immer die oberste offene Aufgabe bearbeiten, außer ich sage etwas anderes.

## Stack
Python 3.12 (uv), dlt, DuckDB, dbt-duckdb, Dagster, LanceDB, sentence-transformers, Ollama, MCP SDK, Streamlit.

## Befehle
- make setup | make demo | make run | make test | make check (ruff + mypy + pytest + dbt build)
- make check baut dbt nur auf Demo-Daten; make dbt-private baut die echten Daten und wird vom Nutzer gestartet
- Windows: ./make.ps1 <target>

## Regeln
- Muss auf Windows und macOS laufen: pathlib, keine bash-only Skripte.
- Keine kostenpflichtigen Dienste; Cloud nur als optionales Profil.
- Niemals Dateien aus data/private/ lesen, ausgeben oder committen.
- Tests zuerst; jede Funktion in src/ hat einen Test, jedes dbt-Modell hat Tests und eine Beschreibung.
- dbt: Namenskonvention stg_/int_/fct_/dim_/mart_, Grain in der Modellbeschreibung.
- Kleine Commits, Conventional Commits mit Anforderungs-ID.
- Bei Unklarheit: nachfragen statt raten; offene Fragen in TODO.md unter "Fragen" notieren.
