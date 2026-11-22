# TODO

Backlog aus `docs/requirements.md`. Pro Session genau eine Aufgabe.

## M0 – Setup
- [x] Repo, `uv`, Makefile und `make.ps1` [RB-02, RB-07]
- [x] pre-commit mit IBAN- und Secret-Prüfung [NFR-05]
- [x] CI-Grundgerüst für Ubuntu und Windows [NFR-03]
- [x] `CLAUDE.md`, `TODO.md`, Projektstruktur [RB-07]

## M1 – Demo-Daten und Ingestion
- [x] Deterministische Demo-Buchungen im Wise-Format, `make demo` [FR-01, RB-05]
- [x] Wise-Import mit YAML-Mapping, Upsert über Bank-ID und EZB-Kursen [FR-02]
- [x] Wise-Mapping mit echtem Export prüfen, besonders Gebühren [FR-02]
- [x] Transfers an eigene Konten erkennen [FR-02]
- [x] Mapping für Raiffeisen Österreich, standardmäßig privat mit lokalen Geschäftsregeln [FR-02]
- [x] Raiffeisen-Regeln mit echtem Export befüllen und prüfen [FR-02]
- [x] Warteschlange für gemischte Händler mit Entscheidung pro Buchung und Teilbeträgen [FR-02, FR-11]
- [ ] Stabilität der Raiffeisen-ID mit einem zweiten, überlappenden Export prüfen [FR-02]
- [x] Mapping für Trade Republic, standardmäßig privat, Investments getrennt [FR-02]
- [x] Trade-Republic-Regeln mit echtem Export befüllen und offene Buchungen entscheiden [FR-02]
- [x] Scalable bewusst nicht importieren: nur Transfers zwischen eigenen Konten, SVS und Steuern laufen über Raiffeisen [FR-02]
- [ ] Markierung für abzuschreibende Anschaffungen über der GWG-Grenze
- [ ] Demo-Rechnungen und Beleg-PDFs [FR-01]
- [ ] Ausgangsrechnungen laden [FR-03]

## M2 – dbt-Modell
- [ ] Seeds für Kategorien, Regeln, Steuerkonfiguration und Kunden
- [x] Staging für Bankbuchungen [NFR-02]
- [x] Intermediate für geschäftliche Beträge und Gebühren [NFR-02]
- [x] Marts `fct_transactions`, `mart_monthly_pnl`, `mart_tax_reserve` mit Unit- und Datentests [FR-17, NFR-02]
- [ ] Marts mit echten Daten bauen und prüfen [NFR-02]
- [ ] Steuerrücklage-Satz mit Steuerberater festlegen, aktuell Platzhalter 30 % [FR-17]
- [ ] Kategorien und regelbasierte Kategorisierung, `dim_category`, `dim_counterparty` [FR-05]
- [ ] Rechnungs-Marts `fct_invoices`, `dim_customer`, `mart_open_invoices` [FR-03]
- [ ] `dbt-expectations` und dbt docs [NFR-02, NFR-09]

## M3 – Orchestrierung und Dashboard
- [ ] Dagster-Assets für Ingestion und dbt [NFR-07]
- [ ] Streamlit-Dashboard, `make run` [FR-10, NFR-01]
- [ ] Pipeline-Laufzeit unter 3 Minuten prüfen [NFR-10]

## M4 – Dokumente und Vektorsuche
- [ ] Beleg-Extraktion aus `inbox/` [FR-04]
- [ ] LanceDB-Index und k-NN-Kategorisierung [FR-06]
- [ ] Beleg-Buchung-Matching [FR-08]
- [ ] Rechnung-Zahlung-Matching [FR-09]

## M5 – LLM-Schicht
- [ ] Provider-Schnittstelle für Ollama und Claude [RB-06]
- [ ] Text-to-SQL mit `sqlglot`, Read-only und Allowlist [FR-12, NFR-04]
- [ ] RAG über Belege mit Quellenangabe [FR-13]
- [ ] Router [FR-14]
- [ ] Eval-Skripte und Testsets [NFR-08]

## M6 – MCP-Server und Semantic Layer
- [ ] MCP-Server mit vier Tools [FR-15]
- [ ] Zentrale Metriken in YAML [FR-16]

## M7 – Portfolio-Feinschliff
- [ ] Review-Oberfläche [FR-11]
- [ ] README, Architekturdiagramm, Demo-GIF, ADRs [NFR-09]

## M8 – Stretch
- [ ] LLM-Fallback für Kategorisierung [FR-07]
- [ ] EÜR-Export [FR-18]
- [ ] Iceberg-Export [FR-19]
- [ ] pgvector-Profil
- [ ] Eigennutzung mit echten Daten

## Fragen
- Steuerlogik für Österreich: Behandlung von SVS, Einkommensteuer und Umsatzsteuer mit Steuerberater abstimmen.
- Welcher Wechselkurs ist steuerlich maßgeblich? Mit Steuerberater abstimmen, Standard sind EZB-Referenzkurse.
- Welches Ollama-Modell für Text-to-SQL?
- Welches mehrsprachige Embedding-Modell?
- Welche Kategorien und Prozentsätze für die Steuerrücklage? Mit Steuerberater abstimmen.
