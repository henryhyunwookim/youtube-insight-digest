"""
YouTube Insight Digest - Cloud Storage & Decoupled Audit Logging Module.

Purpose:
    Manages persistent state (processed video tracking) and operational execution logs
    using Google Cloud Storage (GCS) as the primary source of truth.
    Provides dual-mode fallback:
      1. google-cloud-storage Python SDK
      2. Authenticated `gcloud storage` CLI subprocess
      3. Isolated OS temporary directory fallback (tempfile.gettempdir())
    Zero state or log files are written into the Git repository root.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any


def get_gcs_config() -> tuple[str, str, str]:
    """
    Resolves active GCS bucket name, state blob path, and run log blob path.
    """
    from src.config import GCP_PROJECT_ID, SERVICE_NAME, GCS_BUCKET_NAME

    bucket = GCS_BUCKET_NAME
    if not bucket:
        # Fallback to standard convention
        bucket = f"{GCP_PROJECT_ID}-monitor-data" if GCP_PROJECT_ID else "youtube-insight-data"

    state_blob = f"{SERVICE_NAME}/state.json"
    log_blob = f"{SERVICE_NAME}/run_log.json"
    return bucket, state_blob, log_blob


def get_local_temp_cache_paths() -> tuple[str, str]:
    """
    Returns OS temporary file paths used for local fallback caching.
    Ensures zero workspace clutter.
    """
    temp_dir = tempfile.gettempdir()
    from src.config import SERVICE_NAME
    state_cache = os.path.join(temp_dir, f"{SERVICE_NAME}_state_cache.json")
    log_cache = os.path.join(temp_dir, f"{SERVICE_NAME}_run_log.json")
    return state_cache, log_cache


def load_cloud_state() -> dict[str, Any]:
    """
    Loads state dictionary from GCS with CLI fallback and OS temp cache fallback.
    Returns default schema if no state exists.
    """
    bucket_name, state_blob, _ = get_gcs_config()
    state_cache, _ = get_local_temp_cache_paths()

    # 1. Google Cloud Storage SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(state_blob)
        if blob.exists():
            content = blob.download_as_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                # Sync to temp cache for offline resilience
                try:
                    with open(state_cache, "w", encoding="utf-8") as tf:
                        tf.write(content)
                except Exception:
                    pass
                return data
    except Exception:
        pass

    # 2. Authenticated gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cat", f"gs://{bucket_name}/{state_blob}"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=12,
            shell=is_win
        )
        if res.stdout:
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                try:
                    with open(state_cache, "w", encoding="utf-8") as tf:
                        tf.write(res.stdout)
                except Exception:
                    pass
                return data
    except Exception:
        pass

    # 3. Local OS temp cache fallback
    if os.path.exists(state_cache):
        try:
            with open(state_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

    return {"processed_video_ids": {}, "last_run": None}


def save_cloud_state(state: dict[str, Any]) -> bool:
    """
    Persists state directly to GCS and OS temp cache.
    Returns True if successfully saved to cloud or temp cache.
    """
    bucket_name, state_blob, _ = get_gcs_config()
    state_cache, _ = get_local_temp_cache_paths()

    data_str = json.dumps(state, ensure_ascii=False, indent=2)

    # 1. Always write to OS temp cache
    try:
        with open(state_cache, "w", encoding="utf-8") as f:
            f.write(data_str)
    except Exception as exc:
        print(f"[Storage] Warning: Failed writing to temp cache: {exc}")

    # 2. Upload to GCS via SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(state_blob)
        blob.upload_from_string(data_str, content_type="application/json")
        return True
    except Exception:
        pass

    # 3. Upload to GCS via gcloud CLI fallback
    try:
        is_win = sys.platform == "win32"
        cmd = [
            "gcloud", "storage", "cp",
            state_cache,
            f"gs://{bucket_name}/{state_blob}"
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
            shell=is_win
        )
        return res.returncode == 0
    except Exception:
        pass

    return True


def log_execution(
    success: bool,
    stats: dict[str, Any],
    error: str | None = None,
    trigger_source: str = "cli"
) -> None:
    """
    Appends an operational audit log entry to Cloud Storage and streams structured JSON to stdout.
    Completely decoupled from video processing state.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry: dict[str, Any] = {
        "timestamp": timestamp,
        "success": success,
        "trigger_source": trigger_source,
        "stats": stats,
        "error": error
    }

    # Stream structured output to stdout for Cloud Logging
    try:
        structured_line = json.dumps({"event": "pipeline_execution", **log_entry})
        print(f"[AUDIT_LOG] {structured_line}")
    except Exception:
        pass

    bucket_name, _, log_blob = get_gcs_config()
    _, log_cache = get_local_temp_cache_paths()

    # Load existing log entries
    logs: list[dict[str, Any]] = []

    # 1. Fetch current log history from GCS
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(log_blob)
        if blob.exists():
            content = blob.download_as_text(encoding="utf-8")
            loaded = json.loads(content)
            if isinstance(loaded, list):
                logs = loaded
    except Exception:
        # CLI fallback
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cat", f"gs://{bucket_name}/{log_blob}"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
                shell=is_win
            )
            if res.stdout:
                loaded = json.loads(res.stdout)
                if isinstance(loaded, list):
                    logs = loaded
        except Exception:
            pass

    # Append newest log entry and retain up to last 100 executions
    logs.append(log_entry)
    if len(logs) > 100:
        logs = logs[-100:]

    logs_str = json.dumps(logs, ensure_ascii=False, indent=2)

    # Save to temp cache
    try:
        with open(log_cache, "w", encoding="utf-8") as f:
            f.write(logs_str)
    except Exception:
        pass

    # Save to GCS via SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(log_blob)
        blob.upload_from_string(logs_str, content_type="application/json")
        return
    except Exception:
        pass

    # Save to GCS via CLI fallback
    try:
        is_win = sys.platform == "win32"
        cmd = [
            "gcloud", "storage", "cp",
            log_cache,
            f"gs://{bucket_name}/{log_blob}"
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=12,
            shell=is_win
        )
    except Exception:
        pass
