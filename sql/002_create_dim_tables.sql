CREATE TABLE IF NOT EXISTS core.dim_store (
    store_id      VARCHAR(10)  PRIMARY KEY,
    store_name    VARCHAR(100) NOT NULL,
    region        VARCHAR(50),
    opened_date   DATE,
    is_active     BOOLEAN      DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.dim_product (
    product_id    VARCHAR(10)  PRIMARY KEY,
    product_name  VARCHAR(200) NOT NULL,
    category      VARCHAR(50),
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- Pre-populated once for 2020-2030 by scripts/populate_dim_date.py (Phase 6)
CREATE TABLE IF NOT EXISTS core.dim_date (
    date_id       DATE         PRIMARY KEY,
    year          INTEGER      NOT NULL,
    quarter       INTEGER      NOT NULL,
    month         INTEGER      NOT NULL,
    month_name    VARCHAR(20)  NOT NULL,
    day           INTEGER      NOT NULL,
    day_of_week   INTEGER      NOT NULL,
    day_name      VARCHAR(20)  NOT NULL,
    is_weekend    BOOLEAN      NOT NULL
);
