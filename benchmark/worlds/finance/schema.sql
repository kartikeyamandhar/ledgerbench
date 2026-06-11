-- Finance world schema (DuckDB dialect). Planted preconditions documented in rulebook.yaml.
-- Fiscal year starts in February (offset) and txn timestamps are UTC with a declared
-- reporting timezone: both feed the period/fiscal/timezone trap class.

CREATE TABLE accounts (
    account_id    INTEGER  PRIMARY KEY,
    name          VARCHAR  NOT NULL,
    account_type  VARCHAR  NOT NULL,               -- asset | liability | revenue | expense
    currency      VARCHAR  NOT NULL
);

CREATE TABLE fiscal_periods (
    period_id    INTEGER  PRIMARY KEY,
    fiscal_year  INTEGER  NOT NULL,
    period_no    INTEGER  NOT NULL,                -- 1..12 within the fiscal year
    start_date   DATE     NOT NULL,
    end_date     DATE     NOT NULL
);

CREATE TABLE transactions (
    transaction_id  INTEGER        PRIMARY KEY,
    account_id      INTEGER        NOT NULL REFERENCES accounts (account_id),
    txn_ts          TIMESTAMP      NOT NULL,        -- stored in UTC
    amount          DECIMAL(12, 2) NOT NULL,
    category        VARCHAR        NOT NULL,
    memo            VARCHAR,                         -- NULLABLE: planted nulls
    status          VARCHAR        NOT NULL         -- posted | void | pending
);

-- transactions 1 -> many ledger_entries: summing transactions.amount across this join
-- double-counts (fan trap). The measure is anchored on transactions.
CREATE TABLE ledger_entries (
    entry_id        INTEGER        PRIMARY KEY,
    transaction_id  INTEGER        NOT NULL REFERENCES transactions (transaction_id),
    account_id      INTEGER        NOT NULL REFERENCES accounts (account_id),
    debit           DECIMAL(12, 2) NOT NULL,
    credit          DECIMAL(12, 2) NOT NULL
);
