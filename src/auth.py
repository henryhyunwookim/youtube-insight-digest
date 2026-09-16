"""
YouTube Insight Digest - Authentication Module.

Purpose:
    Manages OAuth 2.0 user credentials for the Google Gmail API. Handles automated
    token refreshes using stored refresh tokens and provides an interactive browser flow
    for initial workstation onboarding.

Lifecycle:
    1. Loads existing credentials from 'token.json' if present.
    2. If credentials exist but are expired, automatically refreshes via Request().
    3. If credentials are missing or revoked:
       - In interactive workstations, launches local server flow using 'credentials.json'.
       - In headless / non-interactive environments, raises a descriptive RuntimeError.
    4. Serializes updated credentials to 'token.json'.
"""

from __future__ import annotations

import os
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import CREDENTIALS_FILE, TOKEN_FILE, SCOPES


def authenticate_gmail() -> Credentials:
    """
    Authenticates with the Google Gmail API using credentials.json and token.json.

    Returns:
        google.oauth2.credentials.Credentials: Valid authenticated Gmail credentials object.

    Raises:
        FileNotFoundError: If 'credentials.json' is missing when initial authorization is required.
        RuntimeError: If running in a headless environment without valid credentials.
    """
    creds: Credentials | None = None

    # Step 1: Attempt to load previously serialized credentials
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            print(f"[Auth] Warning: Could not parse existing token.json: {e}")
            creds = None

    # Step 2: Validate credentials and perform automated token refresh
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[Auth] Access token expired. Attempting automatic refresh via Google Auth...")
                creds.refresh(Request())
                print("[Auth] Access token refreshed successfully.")
            except Exception as e:
                print(f"[Auth] Automated refresh failed: {e}")
                creds = None

        # Step 3: Handle authorization when credentials remain unavailable
        if not creds:
            is_cloud: bool = os.getenv("K_SERVICE") is not None
            is_interactive: bool = bool(sys.stdin and sys.stdin.isatty())

            # In headless environments, browser-based OAuth cannot be performed
            if is_cloud or not is_interactive:
                if TOKEN_FILE.exists():
                    try:
                        TOKEN_FILE.unlink()
                        print("[Auth] Removed invalidated token.json.")
                    except Exception as rm_err:
                        print(f"[Auth] Could not remove token.json: {rm_err}")

                raise RuntimeError(
                    "GMAIL AUTHENTICATION ERROR: token.json is expired or missing and cannot be refreshed "
                    "automatically in a non-interactive environment. Please run the script locally in interactive "
                    "mode first (e.g. 'python -m src.main --auth') to generate a fresh token.json."
                )

            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"'{CREDENTIALS_FILE}' not found. Download OAuth client credentials from "
                    "Google Cloud Console (Desktop application) and save as 'credentials.json' in the repo root."
                )

            print("[Auth] Initiating interactive browser-based OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
            print("[Auth] Authentication successful.")

        # Step 4: Save credentials for subsequent non-interactive runs
        if creds:
            try:
                with open(TOKEN_FILE, "w", encoding="utf-8") as token_out:
                    token_out.write(creds.to_json())
                print(f"[Auth] Updated credentials written to '{TOKEN_FILE.name}'.")
            except Exception as save_err:
                print(f"[Auth] Warning: Could not serialize token.json: {save_err}")

    return creds


if __name__ == "__main__":
    print("[Auth] Testing Gmail authentication flow...")
    try:
        credentials = authenticate_gmail()
        print(f"[Auth] Successfully authenticated! Token valid: {credentials.valid}")
    except Exception as exc:
        print(f"[Auth] Authentication check failed: {exc}")
        sys.exit(1)
