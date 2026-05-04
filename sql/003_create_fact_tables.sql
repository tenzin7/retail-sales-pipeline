-- Landing zone: raw CSV data dumped here before validation and promotion
CREATE TABLE IF NOT EXISTS raw.sales_staging (
    transaction_id  VARCHAR(20),
    store_id        VARCHAR(10),
    product_id      VARCHAR(10),
    product_name    VARCHAR(200),
    category        VARCHAR(50),
    quantity        INTEGER,
    unit_price      NUMERIC(10,2),
    transaction_ts  TIMESTAMP,
    source_file     VARCHAR(255),
    loaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.fact_sales (
    transaction_id  VARCHAR(20)   PRIMARY KEY,
    store_id        VARCHAR(10)   NOT NULL REFERENCES core.dim_store(store_id),
    product_id      VARCHAR(10)   NOT NULL REFERENCES core.dim_product(product_id),
    quantity        INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    revenue         NUMERIC(12,2) NOT NULL,
    transaction_ts  TIMESTAMP     NOT NULL,
    source_file     VARCHAR(255),
    loaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on the columns most commonly used in WHERE and JOIN clauses
CREATE INDEX IF NOT EXISTS idx_fact_sales_ts    ON core.fact_sales(transaction_ts);
CREATE INDEX IF NOT EXISTS idx_fact_sales_store ON core.fact_sales(store_id);

-- One row per pipeline execution — operational audit trail
CREATE TABLE IF NOT EXISTS core.pipeline_runs (
    run_id          SERIAL      PRIMARY KEY,
    run_date        DATE        NOT NULL,
    started_at      TIMESTAMP   NOT NULL,
    finished_at     TIMESTAMP,
    status          VARCHAR(20) NOT NULL,
    rows_extracted  INTEGER,
    rows_loaded     INTEGER,
    error_message   TEXT
);
