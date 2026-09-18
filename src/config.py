"""
YouTube Insight Digest - Configuration Module.

Purpose:
    Loads environment configurations, resolves secrets dynamically from Google Cloud
    Secret Manager with dual-mode fallback (SDK -> gcloud CLI), configures GCS buckets
    for state and operational logging, and manages Gmail OAuth scopes and timezone defaults.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base directory for resolving relative files
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Load local environment variables from .env file if present (for optional local overrides)
load_dotenv(dotenv_path=BASE_DIR / ".env")


def get_gcp_project_id() -> str:
    """
    Resolves the Google Cloud Project ID from environment or ADC/gcloud CLI.
    """
    pid = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid.strip()

    # Attempt resolution via google-auth ADC
    try:
        import google.auth
        _, auth_project = google.auth.default()
        if auth_project:
            return auth_project.strip()
    except Exception:
        pass

    # Attempt resolution via gcloud CLI
    try:
        is_win = sys.platform == "win32"
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
            shell=is_win
        )
        val = res.stdout.strip()
        if val and "(unset)" not in val:
            return val
    except Exception:
        pass

    return ""


# ===========================================================================
# 1. Cloud Project & Service Identifiers
# ===========================================================================
GCP_PROJECT_ID: str = get_gcp_project_id()
GCP_REGION: str = os.getenv("GCP_REGION", "asia-northeast1")
SERVICE_NAME: str = os.getenv("SERVICE_NAME", "youtube-insight-digest")

# GCS Bucket for state & audit logs
# Defaults to project-specific monitor-data or youtube-insight-data
GCS_BUCKET_NAME: str = os.getenv(
    "GCS_BUCKET_NAME",
    f"{GCP_PROJECT_ID}-monitor-data" if GCP_PROJECT_ID else "youtube-insight-data"
)


# ===========================================================================
# 2. Secret Manager Resolution (Dual-Mode Fallback)
# ===========================================================================
def resolve_cloud_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """
    Resolves a secret from GCP Secret Manager via SDK, falling back to gcloud CLI.
    """
    target_project = project_id or GCP_PROJECT_ID
    if not target_project or not secret_id:
        return None

    # Method 1: Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
    except Exception:
        pass

    # Method 2: gcloud CLI fallback (works on any PC logged in via gcloud auth login)
    try:
        is_win = sys.platform == "win32"
        cmd = [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret_id}",
            f"--project={target_project}",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            shell=is_win
        )
        return res.stdout.strip()
    except Exception:
        pass

    return None


def get_gemini_api_key() -> str | None:
    """
    Resolves Gemini API key from local environment or Secret Manager.
    """
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key:
        return key

    # Auto-resolve from Secret Manager
    for sec_name in ["gemini-api-key", "GOOGLE_API_KEY", "GEMINI_API_KEY"]:
        cloud_val = resolve_cloud_secret(sec_name)
        if cloud_val:
            return cloud_val

    return None


# ===========================================================================
# 3. Large Language Model (Gemini) Configuration
# ===========================================================================
GEMINI_API_KEY: str | None = get_gemini_api_key()
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ===========================================================================
# 4. Email Delivery & OAuth Scopes
# ===========================================================================
def get_recipient_email() -> str:
    """
    Resolves recipient email from local env or Secret Manager.
    """
    email = os.getenv("RECIPIENT_EMAIL", "")
    if email:
        return email

    cloud_val = resolve_cloud_secret("youtube-insight-recipient-email")
    if cloud_val:
        return cloud_val

    return ""


RECIPIENT_EMAIL: str = get_recipient_email()
RECIPIENT_NAME: str = os.getenv("RECIPIENT_NAME", "AI Practitioner")

# Gmail Scopes:
# - gmail.readonly: Verify authenticated user profile and account identity
# - gmail.send: Dispatch MIME multipart HTML digest emails
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Path to Google OAuth client credentials and token file (optional local fallbacks)
CREDENTIALS_FILE: Path = BASE_DIR / "credentials.json"
TOKEN_FILE: Path = BASE_DIR / "token.json"

# Secret Manager keys for OAuth credentials & user token
SECRET_OAUTH_TOKEN_KEYS: list[str] = [
    "youtube-insight-token",
    "gmail-agent-token",
]

SECRET_OAUTH_CREDENTIALS_KEYS: list[str] = [
    "youtube-insight-credentials",
    "gmail-oauth-credentials",
]


# ===========================================================================
# 5. Channels and State Persistence Paths
# ===========================================================================
CHANNELS_FILE: Path = BASE_DIR / "channels.json"
STATE_FILE: Path = BASE_DIR / "state.json"


# ===========================================================================
# 6. Scheduling & Operational Defaults
# ===========================================================================
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tokyo")
DEFAULT_LOOKBACK_HOURS: int = int(os.getenv("DEFAULT_LOOKBACK_HOURS", "24"))
