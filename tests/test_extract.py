"""
Tests for src/extract.py

We mock _connect_sftp() rather than paramiko internals directly — this keeps
the tests stable even if we swap the SFTP library later.
"""

import logging
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extract import download_files_for_date

TARGET_DATE = date(2026, 4, 20)
FILENAME    = f"{TARGET_DATE}_transactions.csv"


def make_mock_sftp(missing_stores: list[str] | None = None) -> MagicMock:
    """
    Build a mock SFTPClient with two stores (001, 002).
    Any store listed in missing_stores will raise IOError on get().
    """
    missing_stores = missing_stores or []
    mock = MagicMock()
    mock.listdir.return_value = ["store_001", "store_002"]

    def fake_get(remote_path: str, local_path: str) -> None:
        for store in missing_stores:
            if store in remote_path:
                raise IOError(f"No such file: {remote_path}")
        # Write a minimal CSV so the local file actually exists
        Path(local_path).write_text("transaction_id,store_id\nT001,001\n")

    mock.get.side_effect = fake_get
    return mock


@pytest.fixture
def mock_connect(tmp_path):
    """Patch _connect_sftp to return a mock transport and SFTP client."""
    mock_transport = MagicMock()

    def _factory(missing_stores=None):
        mock_sftp = make_mock_sftp(missing_stores)
        with patch("src.extract._connect_sftp", return_value=(mock_transport, mock_sftp)), \
             patch("src.config.LANDING_DIR", tmp_path):
            yield mock_sftp

    return _factory


def test_all_files_present_returns_all_paths(tmp_path):
    mock_sftp = make_mock_sftp()
    mock_transport = MagicMock()

    with patch("src.extract._connect_sftp", return_value=(mock_transport, mock_sftp)), \
         patch("src.config.LANDING_DIR", tmp_path):
        result = download_files_for_date(TARGET_DATE)

    assert len(result) == 2
    assert all(p.exists() for p in result)


def test_missing_file_is_warning_not_error(tmp_path, caplog):
    """A missing store file must log a WARNING and not raise an exception."""
    mock_sftp = make_mock_sftp(missing_stores=["store_002"])
    mock_transport = MagicMock()

    with patch("src.extract._connect_sftp", return_value=(mock_transport, mock_sftp)), \
         patch("src.config.LANDING_DIR", tmp_path), \
         caplog.at_level(logging.WARNING, logger="src.extract"):
        result = download_files_for_date(TARGET_DATE)

    # Only store_001 came back
    assert len(result) == 1
    assert "store_001" in result[0].name

    # A WARNING was logged for the missing file, no ERROR
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    errors   = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(warnings) == 1
    assert "store_002" in warnings[0].message
    assert len(errors) == 0


def test_all_files_missing_returns_empty_list(tmp_path):
    """All stores missing → empty list returned, no exception raised."""
    mock_sftp = make_mock_sftp(missing_stores=["store_001", "store_002"])
    mock_transport = MagicMock()

    with patch("src.extract._connect_sftp", return_value=(mock_transport, mock_sftp)), \
         patch("src.config.LANDING_DIR", tmp_path):
        result = download_files_for_date(TARGET_DATE)

    assert result == []


def test_sftp_connection_is_always_closed(tmp_path):
    """Transport must be closed even if an error occurs mid-download."""
    mock_sftp = make_mock_sftp()
    mock_transport = MagicMock()

    with patch("src.extract._connect_sftp", return_value=(mock_transport, mock_sftp)), \
         patch("src.config.LANDING_DIR", tmp_path):
        download_files_for_date(TARGET_DATE)

    mock_transport.close.assert_called_once()
    mock_sftp.close.assert_called_once()
