"""
YouTube Insight Digest - Configuration Module.

Purpose:
    Loads environment variables, manages Gmail OAuth scopes, file paths for channel
    configurations and processed-video state tracking, and sets timezone defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory for resolving relative config and state files
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Load local environment variables from .env file in project root
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ===========================================================================
# 1. Large Language Model (Gemini) Configuration
# ===========================================================================
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# ===========================================================================
# 2. Email Delivery & OAuth Scopes
# ===========================================================================
RECIPIENT_EMAIL: str = os.getenv("RECIPIENT_EMAIL", "")
RECIPIENT_NAME: str = os.getenv("RECIPIENT_NAME", "AI Practitioner")

# Gmail Scopes:
# - gmail.readonly: Verify authenticated user profile and account identity
# - gmail.send: Dispatch MIME multipart HTML digest emails
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Path to Google OAuth client credentials and token file
CREDENTIALS_FILE: Path = BASE_DIR / "credentials.json"
TOKEN_FILE: Path = BASE_DIR / "token.json"

# ===========================================================================
# 3. Channels and State Persistence Paths
# ===========================================================================
CHANNELS_FILE: Path = BASE_DIR / "channels.json"
STATE_FILE: Path = BASE_DIR / "state.json"

# ===========================================================================
# 4. Scheduling & Operational Defaults
# ===========================================================================
# Target timezone (Japan Standard Time, UTC+9)
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tokyo")

# Default lookback window in hours when scanning RSS feeds
DEFAULT_LOOKBACK_HOURS: int = int(os.getenv("DEFAULT_LOOKBACK_HOURS", "24"))

# Cloud deployment identifiers (optional)
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
GCP_REGION: str = os.getenv("GCP_REGION", "asia-northeast1")
SERVICE_NAME: str = os.getenv("SERVICE_NAME", "youtube-insight-digest")
