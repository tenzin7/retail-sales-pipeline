"""
Single source of truth for all configuration.
All other modules import from here — nothing reads .env directly except this file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Postgres
DB_HOST     = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT     = int(os.getenv("POSTGRES_PORT", 5433))
DB_NAME     = os.getenv("POSTGRES_DB", "retail")
DB_USER     = os.getenv("POSTGRES_USER", "retail")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "retail")

# SFTP
SFTP_HOST      = os.getenv("SFTP_HOST", "localhost")
SFTP_PORT      = int(os.getenv("SFTP_PORT", 2222))
SFTP_USER      = os.getenv("SFTP_USER", "retail")
SFTP_PASSWORD  = os.getenv("SFTP_PASSWORD", "retail")
SFTP_BASE_PATH = os.getenv("SFTP_BASE_PATH", "/incoming")

# Local filesystem
PROJECT_ROOT = Path(__file__).parent.parent
LANDING_DIR  = PROJECT_ROOT / "data" / "landing"
LOG_DIR      = PROJECT_ROOT / "logs"
