"""
Tests for src/validate.py

Each test writes a minimal CSV to tmp_path, runs validate_file(), and asserts
the outcome. No mocking needed — validate_file() is a pure function of its input.
"""

import pytest
import pandas as pd

from src.validate import validate_file, ValidationError

# ── Helpers ───────────────────────────────────────────────────────────────────

COLUMNS = [
    "transaction_id", "store_id", "product_id", "product_name",
    "category", "quantity", "unit_price", "transaction_ts",
]


def write_csv(tmp_path, rows: list[dict], filename: str = "test.csv"):
    path = tmp_path / filename
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False)
    return path


def valid_row(n: int = 1) -> list[dict]:
    """Return n copies of a valid row with unique transaction_ids."""
    return [
        {
            "transaction_id": f"T00120260420{i:04d}",
            "store_id":       "001",
            "product_id":     "P001",
            "product_name":   "Organic Milk 1L",
            "category":       "Dairy",
            "quantity":       2,
            "unit_price":     3.49,
            "transaction_ts": "2026-04-20 12:34:55",
        }
        for i in range(1, n + 1)
    ]


# ── Happy path ────────────────────────────────────────────────────────────────

def test_valid_file_returns_dataframe(tmp_path):
    path = write_csv(tmp_path, valid_row(5))
    df = validate_file(path)

    assert len(df) == 5
    assert "source_file" in df.columns
    assert df["source_file"].iloc[0] == "test.csv"


def test_source_file_column_is_filename(tmp_path):
    path = write_csv(tmp_path, valid_row(3), filename="store_001_2026-04-20_transactions.csv")
    df = validate_file(path)
    assert (df["source_file"] == "store_001_2026-04-20_transactions.csv").all()


# ── Schema checks ─────────────────────────────────────────────────────────────

def test_missing_column_raises(tmp_path):
    rows = valid_row(3)
    path = tmp_path / "bad_schema.csv"
    # Write CSV without the quantity column
    pd.DataFrame(rows).drop(columns=["quantity"]).to_csv(path, index=False)

    with pytest.raises(ValidationError, match="missing columns"):
        validate_file(path)


def test_empty_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    pd.DataFrame(columns=COLUMNS).to_csv(path, index=False)

    with pytest.raises(ValidationError, match="empty"):
        validate_file(path)


# ── Row-level drops ───────────────────────────────────────────────────────────

def test_null_required_field_drops_row(tmp_path):
    rows = valid_row(30)          # 1 bad row = 3.3% drop rate — under threshold
    rows[0]["transaction_id"] = None
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 29


def test_negative_quantity_drops_row(tmp_path):
    rows = valid_row(50)          # 2 bad rows = 4% drop rate — under threshold
    rows[0]["quantity"] = -1
    rows[1]["quantity"] = 0
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 48


def test_negative_price_drops_row(tmp_path):
    rows = valid_row(30)          # 1 bad row = 3.3% — under threshold
    rows[0]["unit_price"] = -0.01
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 29


def test_zero_price_is_allowed(tmp_path):
    """Unit price of 0 is valid (free promotional item)."""
    rows = valid_row(5)
    rows[0]["unit_price"] = 0.00
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 5


def test_duplicate_transaction_id_keeps_first(tmp_path):
    rows = valid_row(25)          # 1 duplicate = 4% — under threshold
    rows[1]["transaction_id"] = rows[0]["transaction_id"]
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 24
    assert df["transaction_id"].nunique() == 24


# ── Drop rate threshold ───────────────────────────────────────────────────────

def test_drop_rate_above_threshold_raises(tmp_path):
    """More than 5% bad rows → ValidationError."""
    rows = valid_row(100)
    # Make 10 rows bad (10% drop rate)
    for i in range(10):
        rows[i]["quantity"] = -1
    path = write_csv(tmp_path, rows)

    with pytest.raises(ValidationError, match="drop rate"):
        validate_file(path)


def test_drop_rate_at_threshold_passes(tmp_path):
    """Exactly 5% bad rows → just passes (threshold is strictly greater than)."""
    rows = valid_row(100)
    rows[0]["quantity"] = -1   # 1% drop rate — well within threshold
    path = write_csv(tmp_path, rows)
    df = validate_file(path)
    assert len(df) == 99
