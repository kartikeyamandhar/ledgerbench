-- SaaS world schema (DuckDB dialect). One row per the grain documented per table.
-- Planted preconditions for the trap taxonomy are documented in rulebook.yaml.

CREATE TABLE customers (
    customer_id  INTEGER       PRIMARY KEY,
    name         VARCHAR       NOT NULL,
    plan         VARCHAR       NOT NULL,           -- starter | pro | enterprise
    region       VARCHAR,                          -- NULLABLE: planted nulls (refusal/definitional realism)
    signup_date  DATE          NOT NULL
);

CREATE TABLE subscriptions (
    subscription_id  INTEGER      PRIMARY KEY,
    customer_id      INTEGER      NOT NULL REFERENCES customers (customer_id),
    plan             VARCHAR      NOT NULL,
    mrr              DECIMAL(10, 2) NOT NULL,
    status           VARCHAR      NOT NULL,         -- active | canceled
    started_on       DATE         NOT NULL,
    canceled_on      DATE
);

CREATE TABLE users (
    user_id       INTEGER  PRIMARY KEY,
    customer_id   INTEGER  NOT NULL REFERENCES customers (customer_id),
    email         VARCHAR  NOT NULL,
    created_date  DATE     NOT NULL
);

CREATE TABLE orders (
    order_id     INTEGER        PRIMARY KEY,
    customer_id  INTEGER        NOT NULL REFERENCES customers (customer_id),
    order_ts     TIMESTAMP      NOT NULL,           -- stored in UTC
    amount       DECIMAL(10, 2) NOT NULL,
    status       VARCHAR        NOT NULL,           -- completed | pending | refunded
    refunded     BOOLEAN        NOT NULL            -- exclusion flag for revenue
);

-- orders 1 -> many shipments: summing orders.amount across this join inflates revenue (fan trap).
CREATE TABLE shipments (
    shipment_id  INTEGER    PRIMARY KEY,
    order_id     INTEGER    NOT NULL REFERENCES orders (order_id),
    shipped_ts   TIMESTAMP  NOT NULL,
    carrier      VARCHAR    NOT NULL
);

CREATE TABLE events (
    event_id    INTEGER    PRIMARY KEY,
    user_id     INTEGER    NOT NULL REFERENCES users (user_id),
    event_ts    TIMESTAMP  NOT NULL,                -- stored in UTC; reporting tz declared in rulebook
    event_type  VARCHAR    NOT NULL
);
