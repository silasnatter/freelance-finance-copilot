# ADR 0001: EUR reporting with ECB reference rates

Status: accepted, 2026-11-22

## Context

Most customer payments arrive in CHF on a multi-currency Wise account, while most expenses are paid in EUR. Revenue and profit need one reporting currency.

## Decision

EUR is the reporting currency. Amounts that are not in EUR are converted with the ECB euro reference rate of the booking day. On days without a published rate, the latest earlier rate is used, up to 7 days back. An import stops if no such rate exists.

The original amount, currency, and applied rate are stored with every transaction. Currency conversions between own balances are neither income nor expense, only their fees count as expenses.

## Consequences

- Reports are reproducible and work offline once the rates are downloaded.
- Reported EUR revenue can differ from the EUR actually received through Wise conversions.
- The tool provides estimates. The rate that applies for tax purposes must be confirmed with a tax advisor.
