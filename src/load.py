"""
Load: move a validated DataFrame into Postgres in a single transaction.

Flow:
  1. Truncate raw.sales_staging        (wipe previous run's staging data)
  2. Bulk insert DataFrame → staging   (full audit copy of what we received)
  3. Upsert core.dim_store             (new stores appear automatically)
  4. Upsert core.dim_product           (product names/categories can change)
  5. Insert core.fact_sales            (ON CONFLICT DO NOTHING = idempotent)

All five steps share one transaction — if any step fails, everything rolls back
and the database is left exactly as it was before the run started.
"""

import logging

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2.extras import execute_values

from src import config

logger = logging.getLogger(__name__)


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )


def run_load(df: pd.DataFrame, conn: psycopg2.extensions.connection) -> int:
    """
    Load validated DataFrame into Postgres.

    Uses the connection as a transaction context: commits on success,
    rolls back on any exception. Does NOT close the connection.

    Returns the number of rows inserted into core.fact_sales.
    """
    with conn:
        _truncate_staging(conn)
        _insert_staging(conn, df)
        _upsert_dim_store(conn, df)
        _upsert_dim_product(conn, df)
        rows_loaded = _insert_fact_sales(conn, df)

    logger.info("Load complete: %d rows in core.fact_sales", rows_loaded)
    return rows_loaded


# ── Private helpers ────────────────────────────────────────────────────────────

def _truncate_staging(conn: psycopg2.extensions.connection) -> None:
    """Wipe staging so it only ever holds the current run's data."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE raw.sales_staging")
    logger.debug("Truncated raw.sales_staging")


def _insert_staging(conn: psycopg2.extensions.connection, df: pd.DataFrame) -> None:
    """Bulk insert all rows into the staging table."""
    cols = [
        "transaction_id", "store_id", "product_id", "product_name",
        "category", "quantity", "unit_price", "transaction_ts", "source_file",
    ]
    rows = [tuple(row) for row in df[cols].values.tolist()]

    sql = """
        INSERT INTO raw.sales_staging
            (transaction_id, store_id, product_id, product_name, category,
             quantity, unit_price, transaction_ts, source_file)
        VALUES %s
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)

    logger.info("Inserted %d rows into raw.sales_staging", len(rows))


def _upsert_dim_store(conn: psycopg2.extensions.connection, df: pd.DataFrame) -> None:
    """
    Insert any new store_ids found in this file.

    The CSV only contains store_id — no store name or region. We insert a
    placeholder name so the NOT NULL constraint is satisfied. ON CONFLICT DO NOTHING
    means we never overwrite real store data that was loaded by another process.
    """
    store_ids = df["store_id"].unique().tolist()
    rows = [(sid, f"Store {sid}") for sid in store_ids]

    sql = """
        INSERT INTO core.dim_store (store_id, store_name)
        VALUES %s
        ON CONFLICT (store_id) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)

    logger.debug("Upserted %d stores into core.dim_store", len(rows))


def _upsert_dim_product(conn: psycopg2.extensions.connection, df: pd.DataFrame) -> None:
    """
    Insert or update products.

    Unlike stores, product names and categories can legitimately change
    (rebranding, recategorisation), so we DO UPDATE on conflict.
    """
    products = (
        df[["product_id", "product_name", "category"]]
        .drop_duplicates(subset="product_id")
    )
    rows = [tuple(row) for row in products.values.tolist()]

    sql = """
        INSERT INTO core.dim_product (product_id, product_name, category)
        VALUES %s
        ON CONFLICT (product_id) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            category     = EXCLUDED.category,
            updated_at   = CURRENT_TIMESTAMP
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)

    logger.debug("Upserted %d products into core.dim_product", len(rows))


def _insert_fact_sales(conn: psycopg2.extensions.connection, df: pd.DataFrame) -> int:
    """
    Insert rows into core.fact_sales.

    Revenue is calculated here (quantity × unit_price) rather than stored in
    the CSV — computed columns shouldn't be trusted from external sources.

    ON CONFLICT DO NOTHING makes this idempotent: re-running for the same date
    skips rows already loaded without raising an error.
    """
    df = df.copy()
    df["revenue"] = df["quantity"] * df["unit_price"]

    cols = [
        "transaction_id", "store_id", "product_id",
        "quantity", "unit_price", "revenue", "transaction_ts", "source_file",
    ]
    rows = [tuple(row) for row in df[cols].values.tolist()]

    sql = """
        INSERT INTO core.fact_sales
            (transaction_id, store_id, product_id,
             quantity, unit_price, revenue, transaction_ts, source_file)
        VALUES %s
        ON CONFLICT (transaction_id) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
        return cur.rowcount  # actual inserts, skipped conflicts not counted
