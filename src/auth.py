"""
YouTube Insight Digest - Authentication Module.

Purpose:
    Manages OAuth 2.0 user credentials for the Google Gmail API in a cloud-native,
    multi-PC portable architecture. Automatically resolves user tokens and client
    credentials from Google Cloud Secret Manager, handles automated in-memory token
    refreshes, synchronizes refreshed tokens back to Secret Manager, and supports
    interactive browser onboarding with zero local file requirements.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import (
    CREDENTIALS_FILE,
    TOKEN_FILE,
    SCOPES,
    GCP_PROJECT_ID,
    SECRET_OAUTH_TOKEN_KEYS,
    SECRET_OAUTH_CREDENTIALS_KEYS,
    resolve_cloud_secret
)


def save_token_to_secret_manager(
    token_json_str: str,
    secret_id: str = "youtube-insight-token",
    project_id: str | None = None
) -> bool:
    """
    Persists refreshed or newly minted OAuth token JSON string to Google Cloud Secret Manager.
    Tries Secret Manager SDK first, then gcloud CLI fallback.
    """
    target_project = project_id or GCP_PROJECT_ID
    if not target_project:
        return False

    # 1. Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager
        from google.api_core import exceptions

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{target_project}"
        secret_path = f"{parent}/secrets/{secret_id}"

        # Ensure secret container exists
        try:
            client.get_secret(request={"name": secret_path})
        except exceptions.NotFound:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}}
                }
            )

        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": token_json_str.encode("utf-8")}
            }
        )
        print(f"[Auth] Successfully saved updated token to Secret Manager '{secret_id}'.")
        return True
    except Exception as sdk_err:
        pass

    # 2. gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        # Check if secret exists; if not, create it
        check_cmd = ["gcloud", "secrets", "describe", secret_id, f"--project={target_project}"]
        check_res = subprocess.run(check_cmd, capture_output=True, text=True, shell=is_win)
        if check_res.returncode != 0:
            create_cmd = ["gcloud", "secrets", "create", secret_id, "--replication-policy=automatic", f"--project={target_project}"]
            subprocess.run(create_cmd, capture_output=True, text=True, check=True, timeout=10, shell=is_win)

        add_cmd = ["gcloud", "secrets", "versions", "add", secret_id, "--data-file=-", f"--project={target_project}"]
        res = subprocess.run(
            add_cmd,
            input=token_json_str,
            capture_output=True,
            text=True,
            check=True,
            timeout=12,
            shell=is_win
        )
        if res.returncode == 0:
            print(f"[Auth] Successfully saved updated token to Secret Manager '{secret_id}' via gcloud CLI.")
            return True
    except Exception as cli_err:
        pass

    return False


def load_token_from_cloud() -> tuple[str | None, str | None]:
    """
    Attempts to retrieve the serialized OAuth user token from Secret Manager.
    Returns tuple of (token_json_string, secret_name_used).
    """
    for secret_name in SECRET_OAUTH_TOKEN_KEYS:
        token_str = resolve_cloud_secret(secret_name)
        if token_str:
            try:
                # Validate that content is valid JSON containing refresh_token or token
                data = json.loads(token_str)
                if isinstance(data, dict) and ("token" in data or "refresh_token" in data):
                    return token_str, secret_name
            except Exception:
                continue
    return None, None


def load_credentials_config_from_cloud() -> dict[str, Any] | None:
    """
    Attempts to retrieve OAuth client credentials JSON from Secret Manager.
    """
    for secret_name in SECRET_OAUTH_CREDENTIALS_KEYS:
        creds_str = resolve_cloud_secret(secret_name)
        if creds_str:
            try:
                data = json.loads(creds_str)
                if isinstance(data, dict) and ("installed" in data or "web" in data):
                    return data
            except Exception:
                continue
    return None


def authenticate_gmail() -> Credentials:
    """
    Authenticates with the Google Gmail API using Secret Manager credentials and tokens,
    with seamless local file and OS temp directory fallbacks.

    Returns:
        google.oauth2.credentials.Credentials: Valid authenticated Gmail credentials object.

    Raises:
        RuntimeError: If running in a headless environment without valid credentials.
    """
    creds: Credentials | None = None
    token_secret_name: str | None = None

    # Step 1: Attempt to load from Secret Manager first (single source of truth)
    token_str, token_secret_name = load_token_from_cloud()
    if token_str:
        try:
            token_info = json.loads(token_str)
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            print(f"[Auth] Loaded Gmail token from Secret Manager ({token_secret_name}).")
        except Exception as parse_err:
            print(f"[Auth] Warning: Could not parse token from Secret Manager: {parse_err}")
            creds = None

    # Step 1b: Local file fallback if not found in Secret Manager
    if not creds and TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            print("[Auth] Loaded Gmail token from local 'token.json' fallback.")
        except Exception as file_err:
            print(f"[Auth] Warning: Could not parse local token.json: {file_err}")
            creds = None

    # Step 2: Validate credentials and perform automated token refresh
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[Auth] Access token expired. Attempting automatic refresh via Google Auth...")
                creds.refresh(Request())
                print("[Auth] Access token refreshed successfully.")

                # Synchronize refreshed token back to Secret Manager
                primary_secret = token_secret_name or "youtube-insight-token"
                save_token_to_secret_manager(creds.to_json(), secret_id=primary_secret)

                # Also update local file if it already exists
                if TOKEN_FILE.exists():
                    try:
                        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                            f.write(creds.to_json())
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Auth] Automated refresh failed: {e}")
                creds = None

        # Step 3: Handle interactive authorization if credentials remain unavailable
        if not creds:
            is_cloud: bool = os.getenv("K_SERVICE") is not None
            is_interactive: bool = bool(sys.stdin and sys.stdin.isatty())

            if is_cloud or not is_interactive:
                raise RuntimeError(
                    "GMAIL AUTHENTICATION ERROR: OAuth token is expired or missing in Google Cloud Secret Manager "
                    "and cannot be refreshed automatically in a headless environment. Run 'python -m src.main --auth' "
                    "or 'python -m src.sync_secrets' to synchronize valid credentials."
                )

            # Interactive browser-based OAuth flow
            print("[Auth] Resolving client configuration for interactive browser OAuth...")
            client_config = load_credentials_config_from_cloud()
            flow = None

            if client_config:
                print("[Auth] Initializing flow from Secret Manager client credentials...")
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            elif CREDENTIALS_FILE.exists():
                print(f"[Auth] Initializing flow from local '{CREDENTIALS_FILE.name}'...")
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            else:
                raise FileNotFoundError(
                    "OAuth client configuration not found in Secret Manager ('youtube-insight-credentials' / "
                    "'gmail-oauth-credentials') and 'credentials.json' is missing from the workspace root."
                )

            print("[Auth] Initiating interactive browser OAuth consent flow...")
            creds = flow.run_local_server(port=0)
            print("[Auth] Interactive authentication successful.")

            # Step 4: Persist newly authorized credentials directly to Secret Manager
            if creds:
                save_token_to_secret_manager(creds.to_json(), secret_id="youtube-insight-token")
                # Also save to OS temp dir for emergency local caching
                try:
                    temp_token_path = os.path.join(tempfile.gettempdir(), "youtube_insight_token.json")
                    with open(temp_token_path, "w", encoding="utf-8") as tf:
                        tf.write(creds.to_json())
                except Exception:
                    pass

    return creds


if __name__ == "__main__":
    print("[Auth] Testing Gmail cloud authentication flow...")
    try:
        credentials = authenticate_gmail()
        print(f"[Auth] Successfully authenticated! Token valid: {credentials.valid}")
    except Exception as exc:
        print(f"[Auth] Authentication check failed: {exc}")
        sys.exit(1)
