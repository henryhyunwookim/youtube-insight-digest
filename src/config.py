"""
YouTube Insight Digest - Configuration Module.

Purpose:
    Loads environment configurations, resolves secrets dynamically from Google Cloud
    Secret Manager with dual-mode fallback (SDK -> gcloud CLI), configures GCS buckets
    for state and operational logging, and manages Gmail OAuth scopes and timezone defaults.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

# Base directory for resolving relative files
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Optional local environment overrides if present
if (BASE_DIR / ".env").exists():
    load_dotenv(dotenv_path=BASE_DIR / ".env")


def get_gcp_project_id() -> str:
    """
    Resolves the Google Cloud Project ID from environment, gcloud CLI, or ADC.
    """
    pid = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if pid:
        return pid.strip()

    # When running locally, gcloud CLI config is the fastest and primary source of truth
    if not os.getenv("K_SERVICE"):
        try:
            is_win = sys.platform == "win32"
            res = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
                shell=is_win
            )
            val = res.stdout.strip()
            if val and "(unset)" not in val:
                return val
        except Exception:
            pass

    # Attempt resolution via google-auth ADC / Cloud Run metadata service
    try:
        import google.auth
        _, auth_project = google.auth.default()
        if auth_project:
            return auth_project.strip()
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
# 2. Secret Manager Resolution (Fast Multi-Mode with In-Memory Caching)
# ===========================================================================
_SECRETS_CACHE: dict[str, str] = {}
_CACHED_GCLOUD_TOKEN: str | None = None
_CACHED_TOKEN_EXPIRY: float = 0.0


def get_gcloud_access_token() -> str | None:
    """
    Retrieves and caches an OAuth 2.0 access token via gcloud CLI.
    Cached in-memory for 50 minutes to eliminate repeated subprocess overhead.
    """
    global _CACHED_GCLOUD_TOKEN, _CACHED_TOKEN_EXPIRY
    now = time.time()
    if _CACHED_GCLOUD_TOKEN and now < _CACHED_TOKEN_EXPIRY:
        return _CACHED_GCLOUD_TOKEN

    try:
        is_win = sys.platform == "win32"
        res = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=25,
            shell=is_win
        )
        token = res.stdout.strip()
        if token and not token.startswith("ERROR"):
            _CACHED_GCLOUD_TOKEN = token
            _CACHED_TOKEN_EXPIRY = now + 3000.0  # 50 minutes
            return token
    except Exception:
        pass
    return None


def resolve_cloud_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """
    Resolves a secret from GCP Secret Manager via:
      1. In-memory cache (_SECRETS_CACHE)
      2. Cloud Run native environment / SDK (if K_SERVICE is set)
      3. Fast Secret Manager REST API with cached gcloud access token (for local execution)
      4. Standard Secret Manager SDK (with quota project)
      5. Direct gcloud CLI fallback with generous timeout
    """
    target_project = project_id or GCP_PROJECT_ID
    if not target_project or not secret_id:
        return None

    cache_key = f"{target_project}:{secret_id}"
    if cache_key in _SECRETS_CACHE:
        return _SECRETS_CACHE[cache_key]

    # Mode A: If running in Cloud Run, use the native SDK immediately
    if os.getenv("K_SERVICE"):
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name}, timeout=5.0)
            val = response.payload.data.decode("utf-8").strip()
            _SECRETS_CACHE[cache_key] = val
            return val
        except Exception:
            pass

    # Mode B: When running locally, use cached gcloud access token + REST API
    # This avoids gRPC ADC invalid_grant errors and runs in ~0.3s per secret!
    token = get_gcloud_access_token()
    if token:
        try:
            url = f"https://secretmanager.googleapis.com/v1/projects/{target_project}/secrets/{secret_id}/versions/latest:access"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                val = base64.b64decode(data["payload"]["data"]).decode("utf-8").strip()
                _SECRETS_CACHE[cache_key] = val
                return val
        except Exception:
            pass

    # Mode C: Secret Manager Python SDK (with quota_project_id)
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient(
            client_options=ClientOptions(quota_project_id=target_project)
        )
        name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name}, timeout=8.0)
        val = response.payload.data.decode("utf-8").strip()
        _SECRETS_CACHE[cache_key] = val
        return val
    except Exception:
        pass

    # Mode D: gcloud CLI fallback with generous 30s timeout
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
            timeout=30,
            shell=is_win
        )
        val = res.stdout.strip()
        if val:
            _SECRETS_CACHE[cache_key] = val
            return val
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
