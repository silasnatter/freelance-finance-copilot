# Freelancer Finance Copilot

Local-first analytics platform for freelance finances. Bank transactions and receipts are loaded, modeled with dbt, and made queryable through a dashboard and an LLM interface (text-to-SQL, RAG, MCP).

> **Status:** M3. Bank imports, dbt marts, Dagster pipeline and dashboard work. The text-to-SQL chat works. Invoices, receipts, RAG and MCP are not implemented yet. See [TODO.md](TODO.md).

This project is not tax advice. It does not file tax returns.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Docker is optional.

```bash
make setup
make demo
make run
```

`make run` builds the pipeline on synthetic data and opens the dashboard at `http://localhost:8501`. On Windows, use `./make.ps1 <target>`.

| Command | Purpose |
| --- | --- |
| `make run-private` | Pipeline and dashboard with your own data |
| `make dagster` | Dagster UI with lineage and run status on demo data |
| `make dagster-private` | Dagster UI with your own data |
| `make check` | Lint, types, tests and dbt on demo data |

Dashboard and Dagster bind to `127.0.0.1`, and their usage telemetry is turned off.

## Import a Wise export

Save the CSV in `data/private/`, then run:

```bash
uv run python -m finance_copilot fetch-fx
uv run python -m finance_copilot ingest --bank wise --file data/private/wise-transactions-2026.csv
```

Repeated and overlapping imports are safe. Reporting currency is EUR, using ECB reference rates.

To keep transfers between your own accounts out of revenue and expenses, copy `config/own_accounts.example.yaml` to `data/private/own_accounts.yaml` and list your account holder names.

## Import a mixed-use account

Accounts that also carry private spending, such as Raiffeisen, are private by default. Copy `config/business_rules.example.yaml` to `data/private/business_rules.yaml`, list your customers, vendors and tax payees, then run:

```bash
uv run python -m finance_copilot ingest --bank raiffeisen --file data/private/raiffeisen-2026.csv
uv run python -m finance_copilot ingest --bank trade_republic --file data/private/trade-republic-2026.csv
uv run python -m finance_copilot review
```

Trade Republic investments, interest and dividends are stored as `investment` and never count as business income or expenses.

`review` lists the most frequent unassigned counterparties. It only runs in a real terminal, so personal data does not end up in logs or AI chats.

Vendors with both private and business purchases go under `mixed`. Their bookings stay open and do not count until you decide each one, fully or as a partial amount:

```bash
uv run python -m finance_copilot decide
```

Decisions are stored in `data/private/booking_decisions.yaml` and survive re-imports.

## Build the reports

`make check` and CI build the dbt models on demo data only. To build them from your own imported data:

```bash
make dbt-private       # Windows: ./make.ps1 dbt-private
```

This creates `marts.mart_monthly_pnl` and `marts.mart_tax_reserve`.

## Safety pot

The dashboard shows how much should be on your savings account if you move a fixed share of all income there and pay insurance and tax from it. Copy `config/reserve.example.yaml` to `data/private/reserve.yaml`, enter your start balance, and list insurance payees under `reserve_paid` in `business_rules.yaml`. Interest is not included, and this is not tax advice.

## Cost categories

Categories are defined in `config/categories.yaml`. To assign your vendors, copy `config/category_rules.example.yaml` to `data/private/category_rules.yaml`, then rerun the import. `uv run python -m finance_copilot review --uncategorized` lists business costs without a category. It only runs in a real terminal.

## Finance chat

Ask questions in natural language on the `Chat` page of the dashboard. A local Ollama model writes the SQL, and the numbers come directly from the database.

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5-coder:3b
make run
```

The model only receives table structures, never row values. Queries are limited to reads on the marts and run on a connection without write or file access. `make eval` measures the model on 20 demo questions; the current result is 19/20.

## Privacy

Real financial data belongs only in `data/private/` and `inbox/`, which are gitignored. A pre-commit hook blocks IBANs, secrets, and warehouse files.

## Documentation

- [Requirements](docs/requirements.md)
- [Backlog](TODO.md)
- [Architecture decisions](docs/adr/)

## License

[MIT](LICENSE)
