"""
Validate: read a CSV, enforce schema and data quality rules, return a clean DataFrame.

Two outcomes:
  - ValidationError raised  → caller skips this file entirely
  - DataFrame returned      → safe to load into staging

Drop rate threshold exists because silently losing 40% of a file is worse than
failing loud and alerting someone to investigate the source.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DROP_RATE_THRESHOLD = 0.05

EXPECTED_COLUMNS = {
    "transaction_id", "store_id", "product_id", "product_name",
    "category", "quantity", "unit_price", "transaction_ts",
}

# Rows missing any of these are unusable — drop them
REQUIRED_FIELDS = [
    "transaction_id", "store_id", "product_id", "product_name",
    "quantity", "unit_price", "transaction_ts",
]


class ValidationError(Exception):
    pass


def _drop_and_log(df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
    """Keep rows where mask is True; log how many were dropped."""
    dropped = (~mask).sum()
    if dropped:
        logger.warning("Dropped %d rows: %s", dropped, reason)
    return df[mask]


def validate_file(path: Path) -> pd.DataFrame:
    """
    Read and validate a single CSV file.

    Raises ValidationError if:
    - Any expected column is missing
    - The file is empty
    - More than 5% of rows are dropped for any reason

    Returns a clean DataFrame with a source_file column added, ready for staging.
    """
    df = pd.read_csv(path)
    logger.info("Read %s: %d rows", path.name, len(df))

    # ── 1. Schema check ───────────────────────────────────────────────────────
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValidationError(f"{path.name}: missing columns {missing}")

    if len(df) == 0:
        raise ValidationError(f"{path.name}: file is empty")

    initial_count = len(df)

    # ── 2. Coerce types (invalid values become NaN, caught by null check next) ─
    df["quantity"]       = pd.to_numeric(df["quantity"],   errors="coerce")
    df["unit_price"]     = pd.to_numeric(df["unit_price"], errors="coerce")
    df["transaction_ts"] = pd.to_datetime(df["transaction_ts"], errors="coerce")

    # ── 3. Drop rows with nulls in required fields ────────────────────────────
    df = _drop_and_log(df, df[REQUIRED_FIELDS].notna().all(axis=1), "null in required field")

    # ── 4. Drop non-positive quantities ───────────────────────────────────────
    df = _drop_and_log(df, df["quantity"] > 0, "quantity <= 0")

    # ── 5. Drop negative prices ───────────────────────────────────────────────
    df = _drop_and_log(df, df["unit_price"] >= 0, "unit_price < 0")

    # ── 6. Drop duplicate transaction_ids within this file (keep first) ───────
    before = len(df)
    df = df.drop_duplicates(subset=["transaction_id"], keep="first")
    dupes = before - len(df)
    if dupes:
        logger.warning("Dropped %d duplicate transaction_ids", dupes)

    # ── 7. Drop rate guard ────────────────────────────────────────────────────
    total_dropped = initial_count - len(df)
    drop_rate = total_dropped / initial_count
    if drop_rate > DROP_RATE_THRESHOLD:
        raise ValidationError(
            f"{path.name}: drop rate {drop_rate:.1%} exceeds {DROP_RATE_THRESHOLD:.0%} threshold "
            f"({total_dropped} of {initial_count} rows dropped)"
        )

    # ── 8. Add source traceability column ─────────────────────────────────────
    df["source_file"] = path.name

    logger.info(
        "Validated %s: %d → %d rows (dropped %d)",
        path.name, initial_count, len(df), total_dropped
    )
    return df
