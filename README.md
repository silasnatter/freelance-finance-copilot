# Freelancer Finance Copilot

Local-first analytics platform for freelance finances. Bank transactions and receipts are loaded, modeled with dbt, and made queryable through a dashboard and an LLM interface (text-to-SQL, RAG, MCP).

> **Status:** M1 in progress. Wise import and demo transactions work. The dbt marts, dashboard and AI layer are not implemented yet. See [TODO.md](TODO.md).

This project is not tax advice. It does not file tax returns.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Docker is optional.

```bash
make setup
make check
```

On Windows, use `./make.ps1 setup` and `./make.ps1 check`.

## Import a Wise export

Save the CSV in `data/private/`, then run:

```bash
uv run python -m finance_copilot fetch-fx
uv run python -m finance_copilot ingest --bank wise --file data/private/wise-transactions-2026.csv
```

Repeated and overlapping imports are safe. Reporting currency is EUR, using ECB reference rates.

To keep transfers between your own accounts out of revenue and expenses, copy `config/own_accounts.example.yaml` to `data/private/own_accounts.yaml` and list your account holder names.

## Privacy

Real financial data belongs only in `data/private/` and `inbox/`, which are gitignored. A pre-commit hook blocks IBANs, secrets, and warehouse files.

## Documentation

- [Requirements](docs/requirements.md)
- [Backlog](TODO.md)
- [Architecture decisions](docs/adr/)

## License

[MIT](LICENSE)
