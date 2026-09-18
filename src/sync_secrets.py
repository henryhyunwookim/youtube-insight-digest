"""
YouTube Insight Digest - Secret & State Cloud Synchronization Utility.

Purpose:
    Enables single-command multi-PC migration:
    1. Reads existing local workspace credentials (token.json, credentials.json, .env).
    2. Uploads secrets to Google Cloud Secret Manager under descriptive canonical IDs:
       - 'youtube-insight-token'
       - 'youtube-insight-credentials'
       - 'gemini-api-key'
       - 'youtube-insight-recipient-email'
    3. Verifies or provisions the target Google Cloud Storage bucket for state and logs.
    4. Migrates existing local state.json to GCS if present.
    5. Verifies end-to-end cloud resolution.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.config import (
    BASE_DIR,
    GCP_PROJECT_ID,
    GCP_REGION,
    GCS_BUCKET_NAME,
    SERVICE_NAME,
    CREDENTIALS_FILE,
    TOKEN_FILE,
    STATE_FILE,
    resolve_cloud_secret,
)
from src.storage import load_cloud_state, save_cloud_state


def upsert_secret(secret_id: str, secret_value: str, project_id: str) -> bool:
    """
    Creates or updates a secret in Google Cloud Secret Manager.
    Dual-mode: Secret Manager SDK first, then gcloud CLI.
    """
    if not secret_value:
        print(f"[Sync] Skipping '{secret_id}': empty payload.")
        return False

    secret_value_str = secret_value.strip()

    # 1. Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager
        from google.api_core import exceptions

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}"
        secret_path = f"{parent}/secrets/{secret_id}"

        # Ensure secret container exists
        try:
            client.get_secret(request={"name": secret_path})
        except exceptions.NotFound:
            print(f"[Sync] Creating Secret Manager container '{secret_id}'...")
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
                "payload": {"data": secret_value_str.encode("utf-8")}
            }
        )
        print(f"[Sync] -> Successfully synced secret '{secret_id}' via SDK.")
        return True
    except Exception as sdk_err:
        pass

    # 2. gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        check_cmd = ["gcloud", "secrets", "describe", secret_id, f"--project={project_id}"]
        res_check = subprocess.run(check_cmd, capture_output=True, text=True, shell=is_win)

        if res_check.returncode != 0:
            print(f"[Sync] Creating Secret Manager container '{secret_id}' via gcloud...")
            create_cmd = [
                "gcloud", "secrets", "create", secret_id,
                "--replication-policy=automatic",
                f"--project={project_id}"
            ]
            subprocess.run(create_cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)

        add_cmd = [
            "gcloud", "secrets", "versions", "add", secret_id,
            "--data-file=-",
            f"--project={project_id}"
        ]
        res_add = subprocess.run(
            add_cmd,
            input=secret_value_str,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
            shell=is_win
        )
        if res_add.returncode == 0:
            print(f"[Sync] -> Successfully synced secret '{secret_id}' via gcloud CLI.")
            return True
    except Exception as cli_err:
        print(f"[Sync] Error syncing secret '{secret_id}': {cli_err}")

    return False


def ensure_gcs_bucket(bucket_name: str, project_id: str, region: str) -> bool:
    """
    Verifies that the target GCS bucket exists; creates it if absent.
    """
    print(f"[Sync] Verifying GCS bucket: gs://{bucket_name}...")
    # SDK check
    try:
        from google.cloud import storage

        client = storage.Client(project=project_id)
        bucket = client.bucket(bucket_name)
        if bucket.exists():
            print(f"[Sync] -> GCS bucket gs://{bucket_name} exists and is accessible.")
            return True

        print(f"[Sync] Creating GCS bucket gs://{bucket_name} in location {region}...")
        client.create_bucket(bucket, location=region)
        print(f"[Sync] -> Successfully created GCS bucket gs://{bucket_name}.")
        return True
    except Exception:
        pass

    # gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        check_cmd = ["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}"]
        res = subprocess.run(check_cmd, capture_output=True, text=True, shell=is_win)
        if res.returncode == 0:
            print(f"[Sync] -> GCS bucket gs://{bucket_name} verified via gcloud CLI.")
            return True

        create_cmd = [
            "gcloud", "storage", "buckets", "create",
            f"gs://{bucket_name}",
            f"--project={project_id}",
            f"--location={region}"
        ]
        res_create = subprocess.run(create_cmd, capture_output=True, text=True, check=True, timeout=20, shell=is_win)
        if res_create.returncode == 0:
            print(f"[Sync] -> Successfully created GCS bucket gs://{bucket_name} via gcloud CLI.")
            return True
    except Exception as e:
        print(f"[Sync] Notice: Bucket verification notice: {e}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize local secrets and state to Google Cloud.")
    parser.add_argument("--project", type=str, default=GCP_PROJECT_ID, help="Target GCP Project ID")
    parser.add_argument("--bucket", type=str, default=GCS_BUCKET_NAME, help="Target GCS Bucket Name")
    parser.add_argument("--region", type=str, default=GCP_REGION, help="GCP Region for GCS bucket")
    args = parser.parse_args()

    project_id = args.project
    if not project_id:
        print("[Sync Error] No GCP Project ID configured or detected. Please run 'gcloud config set project <id>'", file=sys.stderr)
        sys.exit(1)

    print("===========================================================================")
    print(" YouTube Insight Digest - Cloud Migration & Secret Synchronization")
    print(f" Target Project: {project_id}")
    print(f" Target GCS:     gs://{args.bucket}")
    print("===========================================================================")

    # 1. Sync token.json
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token_data = f.read()
            print("[Sync] Synchronizing 'token.json' to Secret Manager ('youtube-insight-token')...")
            upsert_secret("youtube-insight-token", token_data, project_id)
        except Exception as e:
            print(f"[Sync] Warning reading token.json: {e}")
    else:
        print("[Sync] Note: 'token.json' not found locally. Checking cloud presence...")
        existing = resolve_cloud_secret("youtube-insight-token", project_id) or resolve_cloud_secret("gmail-agent-token", project_id)
        if existing:
            print("[Sync] -> OAuth token is already active in Secret Manager.")
        else:
            print("[Sync] -> OAuth token not found. Run 'python -m src.main --auth' locally to generate.")

    # 2. Sync credentials.json
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                creds_data = f.read()
            print("[Sync] Synchronizing 'credentials.json' to Secret Manager ('youtube-insight-credentials')...")
            upsert_secret("youtube-insight-credentials", creds_data, project_id)
        except Exception as e:
            print(f"[Sync] Warning reading credentials.json: {e}")
    else:
        print("[Sync] Note: 'credentials.json' not found locally. Checking cloud presence...")
        existing = resolve_cloud_secret("youtube-insight-credentials", project_id) or resolve_cloud_secret("gmail-oauth-credentials", project_id)
        if existing:
            print("[Sync] -> OAuth client credentials already present in Secret Manager.")

    # 3. Sync .env secrets (GEMINI_API_KEY / RECIPIENT_EMAIL)
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v:
                    print("[Sync] Synchronizing Gemini API key to Secret Manager ('gemini-api-key')...")
                    upsert_secret("gemini-api-key", v, project_id)
                elif k == "RECIPIENT_EMAIL" and v:
                    print("[Sync] Synchronizing recipient email to Secret Manager ('youtube-insight-recipient-email')...")
                    upsert_secret("youtube-insight-recipient-email", v, project_id)
        except Exception as e:
            print(f"[Sync] Warning reading .env: {e}")

    # 4. Verify/Ensure GCS bucket
    ensure_gcs_bucket(args.bucket, project_id, args.region)

    # 5. Migrate local state.json if present
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            if isinstance(state_data, dict):
                print(f"[Sync] Migrating local 'state.json' ({len(state_data.get('processed_video_ids', {}))} videos) to GCS...")
                save_cloud_state(state_data)
                print("[Sync] -> State successfully uploaded to Google Cloud Storage.")
        except Exception as e:
            print(f"[Sync] Warning migrating state.json: {e}")

    print("===========================================================================")
    print(" Cloud Synchronization Finished.")
    print("===========================================================================")


if __name__ == "__main__":
    main()
