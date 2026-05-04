"""
Extract: connect to SFTP, download CSVs for a target date, return local paths.

Design decisions:
- Missing store files are warnings, not errors — one late store shouldn't
  block the rest of the pipeline.
- If zero files download successfully, the caller (main.py) raises an error.
- A private _connect_sftp() makes it easy to mock in tests without patching
  deep into the paramiko internals.
"""

import logging
from datetime import date
from pathlib import Path

import paramiko

from src import config

logger = logging.getLogger(__name__)


def _connect_sftp() -> tuple[paramiko.Transport, paramiko.SFTPClient]:
    """Open an SFTP connection. Caller must close transport when done."""
    transport = paramiko.Transport((config.SFTP_HOST, config.SFTP_PORT))
    transport.connect(username=config.SFTP_USER, password=config.SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    return transport, sftp


def _list_store_dirs(sftp: paramiko.SFTPClient) -> list[str]:
    """Return sorted store subdirectory names under the SFTP base path."""
    try:
        entries = sftp.listdir(config.SFTP_BASE_PATH)
        stores = sorted(e for e in entries if e.startswith("store_"))
        logger.info("Found %d store directories on SFTP", len(stores))
        return stores
    except IOError as e:
        logger.error("Cannot list SFTP path %s: %s", config.SFTP_BASE_PATH, e)
        return []


def download_files_for_date(target_date: date) -> list[Path]:
    """
    Download all store CSV files for target_date from SFTP.

    Each store uploads: /incoming/store_NNN/YYYY-MM-DD_transactions.csv
    Files land locally at:  data/landing/YYYY-MM-DD/store_NNN_YYYY-MM-DD_transactions.csv

    Missing files are logged as WARNING and skipped — not every store uploads
    on time, and one absence shouldn't crash the pipeline for everyone else.

    Returns the list of local Paths for files that were successfully downloaded.
    """
    landing_dir = config.LANDING_DIR / str(target_date)
    landing_dir.mkdir(parents=True, exist_ok=True)

    transport, sftp = _connect_sftp()
    downloaded: list[Path] = []

    try:
        store_dirs = _list_store_dirs(sftp)
        filename = f"{target_date}_transactions.csv"

        for store_dir in store_dirs:
            remote_path = f"{config.SFTP_BASE_PATH}/{store_dir}/{filename}"
            local_path  = landing_dir / f"{store_dir}_{filename}"

            try:
                sftp.get(remote_path, str(local_path))
                logger.info("Downloaded %s → %s", remote_path, local_path.name)
                downloaded.append(local_path)
            except IOError:
                logger.warning("Missing file on SFTP: %s", remote_path)

    finally:
        sftp.close()
        transport.close()

    logger.info(
        "Extract complete: %d of %d files downloaded for %s",
        len(downloaded), len(store_dirs), target_date
    )
    return downloaded
