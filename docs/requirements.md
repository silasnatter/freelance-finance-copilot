# Freelancer Finance Copilot – Requirements

Nov 22, 2026 · @silas

## 1. Projektüberblick

Der Freelancer Finance Copilot ist eine lokal laufende Analytics-Plattform für die eigenen Freelance-Finanzen: Bankumsätze und Belege werden geladen, mit dbt modelliert und über ein Dashboard sowie ein LLM-Interface (Text-to-SQL, RAG, MCP) abfragbar gemacht.

**Ziele**

- Portfolio: Ein End-to-End-Projekt auf GitHub, das modernes Analytics Engineering (dbt, Tests, CI) und eine AI-Schicht (Vektorsuche, RAG, MCP) zeigt.
- Eigennutzung: Einnahmen, Ausgaben, offene Rechnungen und Steuerrücklagen jederzeit im Blick; Vorbereitung der Einnahmen-Ausgaben-Rechnung.
- Lernen: Dagster, dlt, pgvector/LanceDB, MCP und Data Contracts praktisch anwenden.

**Nicht-Ziele**

- Keine Steuerberatung und keine automatische Abgabe von Steuererklärungen.
- Keine Multi-User-SaaS, kein Login-System, keine Bank-API-Anbindung (PSD2) in Version 1.
- Keine mobile App.

**Zielgruppe**

- Primär: ich selbst (Single-User, lokal).
- Sekundär: Recruiter und Hiring Manager, die das Repo und die Demo ansehen.

## 2. Rahmenbedingungen

Das Projekt läuft komplett lokal und kostenlos; Cloud-Dienste sind optional und austauschbar.

| ID | Bedingung | Konsequenz |
| --- | --- | --- |
| RB-01 | 0 € Kosten für Software und Hosting | Nur Open Source oder Free Tiers; jede Cloud-Komponente hat eine lokale Alternative |
| RB-02 | Läuft auf Windows und macOS | Python mit `uv`, Docker Compose für Services, keine Shell-Skripte ohne PowerShell-/Make-Pendant, Pfade über `pathlib` |
| RB-03 | Local-first | Ohne Docker lauffähig mit DuckDB + LanceDB; Postgres/pgvector als optionales Profil |
| RB-04 | Datenschutz | Echte Finanzdaten liegen nur lokal in `data/private/` (gitignored); nie in Commits, Logs oder Prompts an externe LLMs ohne explizites Opt-in |
| RB-05 | Demo-fähig | Synthetische Demo-Daten (Faker) erzeugen das gesamte Projekt reproduzierbar mit einem Befehl |
| RB-06 | LLM-Anbieter austauschbar | Abstraktion über eine Provider-Schnittstelle; lokal via Ollama, optional Claude-API |
| RB-07 | Entwicklung mit Claude Code | `CLAUDE.md` und `TODO.md` im Repo; kleine, testbare Arbeitspakete |

## 3. Tech-Stack

Der Stack setzt auf DuckDB, dbt und Dagster als Kern und legt eine austauschbare AI-Schicht darüber.

| Layer | Technologie | Alternative | Warum |
| --- | --- | --- | --- |
| Sprache / Packaging | Python 3.12, `uv`, `ruff`, `mypy` | Poetry | Schnell, plattformübergreifend, moderner Standard |
| Ingestion | `dlt` (data load tool) | eigene Loader | Schema-Inferenz, inkrementelles Laden, Data-Contract-Modi |
| Storage / Compute | DuckDB (Datei `warehouse.duckdb`) | Postgres, MotherDuck | Embedded, gratis, schnell für Analytics |
| Tabellenformat (Stretch) | Apache Iceberg über DuckDB | Delta Lake | Lakehouse-Kompetenz zeigen |
| Transformation | dbt-core + dbt-duckdb | SQLMesh | Industriestandard für Analytics Engineering |
| Semantic Layer | dbt Semantic Layer / MetricFlow-Definitionen in YAML | Cube | Metriken einmal definieren, von BI und LLM nutzen |
| Orchestrierung | Dagster (Software-defined Assets, dbt-Integration) | Prefect, Airflow | Asset-Lineage, gute lokale UI |
| Data Quality | dbt Tests + `dbt-expectations`, Pydantic für Contracts | Soda, Great Expectations | Qualität als Code |
| Dokumentenverarbeitung | `pypdf` / `docling`, OCR optional via Tesseract | Unstructured | Text aus Beleg-PDFs extrahieren |
| Embeddings | `sentence-transformers` (lokal, mehrsprachig) | Ollama-Embeddings, API | Kostenlos, offline, Deutsch-tauglich |
| Vector DB | LanceDB (lokal, dateibasiert) | pgvector, Qdrant | Kein Server nötig; pgvector-Profil zeigt SQL-Integration |
| LLM | Ollama (z. B. Llama/Qwen) | Claude-API | Lokal und gratis, API optional |
| AI-Orchestrierung | schlanke eigene Schicht oder PydanticAI | LangChain, LlamaIndex | Wenig Magie, gut testbar |
| Agent-Schnittstelle | MCP-Server (Python MCP SDK) | – | Claude Desktop/Code kann den Data Mart direkt abfragen |
| Frontend | Streamlit | Evidence.dev | Dashboard + Chat in einer App |
| Infrastruktur | Docker Compose, GitHub Actions, pre-commit | – | Reproduzierbar, CI für dbt und Python |

Free Tiers von Cloud-Anbietern ändern sich; deshalb ist jede Cloud-Option nur ein Profil, nie Voraussetzung.

## 4. Architektur und Datenfluss

&#91;embedded content: Architektur · Quellen bis Konsumenten\]

Die dbt-Marts sind die einzige Wahrheit: Dashboard, Text-to-SQL und MCP-Server lesen dieselben Tabellen, LanceDB liefert nur den Kontext für RAG und Kategorisierung.

## 5. Datenquellen und Datenmodell

Vier Quellen fliessen in ein Sternschema mit einer zentralen Faktentabelle der Buchungen.

**Datenquellen**

| Quelle | Format | Inhalt | Ladeart |
| --- | --- | --- | --- |
| Bank-Export | CSV (Bank-spezifisch, über Mapping-Config) | Buchungsdatum, Betrag, Gegenpartei, Verwendungszweck, IBAN | inkrementell, Dedup über Hash |
| Ausgangsrechnungen | CSV/JSON oder PDF | Rechnungsnr., Kunde, Netto, USt, Fälligkeit, Status | inkrementell |
| Belege | PDF/Bild in `inbox/` | Eingangsrechnungen, Quittungen | Datei-Watcher bzw. Dagster-Sensor |
| Stammdaten | YAML/CSV-Seeds | Kategorien, Kategorie-Regeln, Steuerkonfiguration, Kunden | dbt seeds |

**dbt-Schichten**

- `staging` – 1:1 je Quelle, Typen und Namen bereinigt: `stg_bank__transactions`, `stg_invoices__outgoing`, `stg_documents__receipts`.
- `intermediate` – Logik: `int_transactions_categorized` (Regeln + Embedding-Vorschlag), `int_receipts_matched` (Beleg ↔ Buchung), `int_invoices_paid` (Rechnung ↔ Zahlungseingang).
- `marts` – für Analyse und LLM:
  - `fct_transactions` (Grain: eine Buchung)
  - `fct_invoices` (Grain: eine Ausgangsrechnung)
  - `dim_category`, `dim_counterparty`, `dim_customer`, `dim_date`
  - `mart_monthly_pnl`, `mart_tax_reserve`, `mart_open_invoices`

**Vektor-Index**

- Collection `documents`: Chunks aus Beleg-PDFs mit Metadaten (Datum, Betrag, Gegenpartei, Beleg-ID).
- Collection `transactions`: Embedding von Gegenpartei + Verwendungszweck für Ähnlichkeits-Kategorisierung.
- Collection `schema_docs`: dbt-Modell- und Spaltenbeschreibungen für Text-to-SQL-Kontext.

## 6. Funktionale Anforderungen

Jede Anforderung hat eine ID, eine Priorität (Must/Should/Could) und ein prüfbares Akzeptanzkriterium, damit Claude Code sie als Arbeitspaket umsetzen und testen kann.

| ID | Anforderung | Prio | Akzeptanzkriterium |
| --- | --- | --- | --- |
| FR-01 | Synthetische Demo-Daten generieren (12 Monate Buchungen, \~30 Rechnungen, \~100 Belege als PDF) | Must | `make demo` erzeugt alle Daten deterministisch (Seed) in `data/demo/` |
| FR-02 | Bank-CSV laden mit konfigurierbarem Spalten-Mapping | Must | Neue Bank = nur neue YAML-Mapping-Datei; doppelter Import erzeugt keine Duplikate |
| FR-03 | Ausgangsrechnungen laden | Must | Rechnungen erscheinen in `fct_invoices` mit Status offen/bezahlt |
| FR-04 | Beleg-PDFs aus `inbox/` verarbeiten (Text extrahieren, Betrag/Datum/Händler erkennen) | Must | ≥ 90 % der Demo-Belege mit korrektem Betrag und Datum |
| FR-05 | Regelbasierte Kategorisierung über Seed-Regeln | Must | Regeln in YAML; Treffer werden mit `source = rule` markiert |
| FR-06 | Embedding-basierte Kategorisierung für nicht erkannte Buchungen (k-NN über bereits kategorisierte) | Must | Vorschlag mit Konfidenz; unter Schwelle → `needs_review` |
| FR-07 | LLM-Fallback für Kategorisierung | Could | Nur wenn k-NN-Konfidenz unter Schwelle; Ergebnis mit `source = llm` |
| FR-08 | Beleg ↔ Buchung matchen (Betrag, Datum ± 7 Tage, Ähnlichkeit der Gegenpartei) | Should | Match-Rate auf Demo-Daten ≥ 85 %; unklare Fälle in Review-Liste |
| FR-09 | Rechnung ↔ Zahlungseingang matchen | Should | Bezahlte Rechnungen automatisch auf `paid` |
| FR-10 | Dashboard: Einnahmen/Ausgaben je Monat, Ausgaben nach Kategorie, offene Rechnungen, Steuerrücklage | Must | Streamlit-Seite lädt in < 2 s auf Demo-Daten |
| FR-11 | Review-Oberfläche zum Korrigieren von Kategorien | Should | Korrektur wird gespeichert und fließt als Trainingsbeispiel in den k-NN-Index |
| FR-12 | Text-to-SQL-Chat über die Marts ("Wie viel Software 2026?") | Must | Nur `SELECT` auf `marts`; generiertes SQL wird angezeigt; 20 Testfragen mit erwarteten Ergebnissen |
| FR-13 | RAG über Belege ("Rechnung vom Hosting im Sommer") mit Quellenangabe | Must | Antwort verlinkt die Beleg-Datei; Top-5-Retrieval-Trefferquote ≥ 80 % auf Testset |
| FR-14 | Router: Frage geht an SQL, RAG oder beides | Should | Korrekte Route bei ≥ 85 % der Testfragen |
| FR-15 | MCP-Server mit Tools `query_marts`, `search_documents`, `list_metrics`, `get_monthly_summary` | Must | In Claude Desktop/Code einbindbar; Doku im README |
| FR-16 | Semantic Layer: Metriken (Umsatz, Ausgaben, Gewinn, Steuerrücklage) zentral in YAML | Should | Dashboard und LLM nutzen dieselben Definitionen |
| FR-17 | Steuerrücklage schätzen (konfigurierbarer Prozentsatz) | Should | Satz in Config; klar als Schätzung gekennzeichnet |
| FR-18 | Export für Einnahmen-Ausgaben-Rechnung (CSV/Excel je Jahr) | Could | Export summiert nach Kategorie und enthält Beleg-Referenzen |
| FR-19 | Iceberg-Export der Marts | Could | Marts als Iceberg-Tabellen lesbar |

## 7. Nicht-funktionale Anforderungen

| ID | Bereich | Anforderung |
| --- | --- | --- |
| NFR-01 | Reproduzierbarkeit | Frischer Clone → `make setup && make demo && make run` läuft auf Windows und macOS ohne manuelle Schritte |
| NFR-02 | Tests | `pytest` für Python (Ziel ≥ 80 % Coverage in `src/`), dbt Tests auf jedem Modell (unique, not\_null, relationships, accepted\_values) |
| NFR-03 | CI | GitHub Actions: lint (`ruff`), Typprüfung (`mypy`), `pytest`, `dbt build` auf Demo-Daten, auf Ubuntu und Windows |
| NFR-04 | Sicherheit | Text-to-SQL nur über Read-only-Verbindung und Allowlist der Mart-Schemas; SQL wird vor Ausführung geparst (`sqlglot`) |
| NFR-05 | Datenschutz | `data/private/`, `.env`, `*.duckdb` in `.gitignore`; pre-commit-Hook prüft auf IBAN-Muster und Secrets |
| NFR-06 | Konfiguration | Alle Einstellungen in `config/*.yaml` + `.env`; keine hartcodierten Pfade |
| NFR-07 | Observability | Strukturiertes Logging; Dagster-UI zeigt Lineage und Laufstatus |
| NFR-08 | Evaluierung | Eval-Skript für Text-to-SQL, RAG und Kategorisierung mit festem Testset; Ergebnisse im README |
| NFR-09 | Dokumentation | README mit Architekturdiagramm, GIF/Screenshots, Quickstart; dbt docs generiert; ADRs in `docs/adr/` |
| NFR-10 | Performance | Vollständiger Pipeline-Lauf auf Demo-Daten < 3 min auf einem Laptop |

## 8. Repo-Struktur

```text
finance-copilot/
├── CLAUDE.md                # Kontext und Regeln für Claude Code
├── TODO.md                  # Backlog, abgeleitet aus diesem Dokument
├── README.md
├── Makefile                 # + make.ps1 für Windows
├── pyproject.toml           # uv-Projekt
├── docker-compose.yml       # optional: postgres+pgvector, ollama
├── config/                  # banks/*.yaml, categories.yaml, settings.yaml
├── data/
│   ├── demo/                # generiert, committed oder per make demo
│   └── private/             # gitignored, echte Daten
├── src/finance_copilot/
│   ├── ingestion/           # dlt-Pipelines
│   ├── documents/           # PDF-Extraktion, Parsing
│   ├── embeddings/          # Embedding-Modell, Vector-Store-Abstraktion
│   ├── llm/                 # Provider (Ollama, Claude), Router, Text-to-SQL, RAG
│   ├── mcp_server/          # MCP-Tools
│   ├── demo_data/           # Faker-Generator
│   └── orchestration/       # Dagster-Definitions
├── dbt/                     # dbt-Projekt (models/staging|intermediate|marts, seeds, tests)
├── app/                     # Streamlit
├── evals/                   # Testfragen + Eval-Skripte
├── tests/
├── docs/adr/
└── .github/workflows/ci.yml
```

## 9. Meilensteine

Zuerst das klassische Fundament, danach die AI-Schicht: Jeder Meilenstein endet mit einem lauffähigen, demo-baren Stand.

1. **M0 – Setup:** Repo, `uv`, Makefile/`make.ps1`, pre-commit, CI-Grundgerüst, `CLAUDE.md`, `TODO.md`.
2. **M1 – Demo-Daten und Ingestion:** FR-01, FR-02, FR-03; DuckDB befüllt.
3. **M2 – dbt-Modell:** staging, intermediate, marts, Seeds, Tests, dbt docs; FR-05.
4. **M3 – Orchestrierung und Dashboard:** Dagster-Assets für Ingestion + dbt; Streamlit-Dashboard (FR-10).
5. **M4 – Dokumente und Vektorsuche:** FR-04, FR-06, FR-08, FR-09; LanceDB-Index.
6. **M5 – LLM-Schicht:** FR-12, FR-13, FR-14 mit Evals (NFR-08).
7. **M6 – MCP-Server und Semantic Layer:** FR-15, FR-16.
8. **M7 – Portfolio-Feinschliff:** README, Architekturdiagramm, Demo-GIF, ADRs, FR-11, FR-17.
9. **M8 – Stretch:** FR-07, FR-18, FR-19, pgvector-Profil, Eigennutzung mit echten Daten.

## 10. Arbeiten mit Claude Code

Dieses Dokument ist die Quelle der Wahrheit; Claude Code arbeitet über `CLAUDE.md` (Regeln) und `TODO.md` (Backlog) daran entlang.

**Workflow**

1. Dieses Dokument als `docs/requirements.md` ins Repo legen.
2. Claude Code bitten: "Lies `docs/requirements.md` und erstelle `TODO.md` mit Aufgaben je Meilenstein, jede mit Bezug auf FR-/NFR-IDs."
3. Pro Session genau eine Aufgabe: zuerst Plan, dann Tests, dann Implementierung, dann `make check`.
4. Nach jeder Aufgabe: Haken in `TODO.md`, Commit mit Conventional-Commit-Message und ID (`feat(ingestion): bank csv mapping [FR-02]`).
5. Architekturentscheidungen als kurze ADR in `docs/adr/` festhalten lassen.

**Vorlage `CLAUDE.md`**

```markdown
# Finance Copilot – Kontext für Claude

## Projekt
Lokale Analytics-Plattform für Freelance-Finanzen. Anforderungen: docs/requirements.md (Quelle der Wahrheit).
Backlog: TODO.md – immer die oberste offene Aufgabe bearbeiten, außer ich sage etwas anderes.

## Stack
Python 3.12 (uv), dlt, DuckDB, dbt-duckdb, Dagster, LanceDB, sentence-transformers, Ollama, MCP SDK, Streamlit.

## Befehle
- make setup | make demo | make run | make test | make check (ruff + mypy + pytest + dbt build)
- Windows: ./make.ps1 <target>

## Regeln
- Muss auf Windows und macOS laufen: pathlib, keine bash-only Skripte.
- Keine kostenpflichtigen Dienste; Cloud nur als optionales Profil.
- Niemals Dateien aus data/private/ lesen, ausgeben oder committen.
- Tests zuerst; jede Funktion in src/ hat einen Test, jedes dbt-Modell hat Tests und eine Beschreibung.
- dbt: Namenskonvention stg_/int_/fct_/dim_/mart_, Grain in der Modellbeschreibung.
- Kleine Commits, Conventional Commits mit Anforderungs-ID.
- Bei Unklarheit: nachfragen statt raten; offene Fragen in TODO.md unter "Fragen" notieren.
```

## 11. Definition of Done und offene Entscheidungen

**Definition of Done (je Aufgabe)**

- [ ] Akzeptanzkriterium der referenzierten FR/NFR erfüllt
- [ ] `make check` grün lokal und in CI (Ubuntu + Windows)
- [ ] Neue dbt-Modelle mit Beschreibung, Grain und Tests
- [ ] README bzw. Doku aktualisiert, falls sich Bedienung ändert
- [ ] Keine echten Daten, Secrets oder IBANs im Diff

**Offene Entscheidungen**

- Welche Bank(en) zuerst? Bestimmt das erste CSV-Mapping.
- Ollama-Modell für Text-to-SQL: Qualität vs. Laptop-Ressourcen (RAM) testen.
- Embedding-Modell: mehrsprachiges Modell für deutsche Belege wählen und auf Testset vergleichen.
- Streamlit oder Evidence.dev für das Dashboard (Streamlit ist gesetzt, falls Chat und Dashboard in einer App bleiben sollen).
- Steuerlogik: welche Kategorien und Prozentsätze für die Rücklage; mit Steuerberater abstimmen, das Tool liefert nur Schätzungen.
- Lizenz des Repos (z. B. MIT).
