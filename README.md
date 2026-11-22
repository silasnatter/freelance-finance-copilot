# Freelancer Finance Copilot

Local-first analytics platform for freelance finances. Bank transactions and receipts are loaded, modeled with dbt, and made queryable through a dashboard and an LLM interface (text-to-SQL, RAG, MCP).

> **Status:** M0, project setup. The data pipeline, dashboard and AI layer are not implemented yet. See [TODO.md](TODO.md).

This project is not tax advice. It does not file tax returns.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Docker is optional.

```bash
make setup
make check
```

On Windows, use `./make.ps1 setup` and `./make.ps1 check`.

## Privacy

Real financial data belongs only in `data/private/` and `inbox/`, which are gitignored. A pre-commit hook blocks IBANs, secrets, and warehouse files.

## Documentation

- [Requirements](docs/requirements.md)
- [Backlog](TODO.md)
- [Architecture decisions](docs/adr/)

## License

[MIT](LICENSE)
