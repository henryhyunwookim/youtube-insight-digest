"""
YouTube Insight Digest - Flask Web Service.

Purpose:
    Exposes an HTTP POST/GET endpoint for automated triggers (e.g. Cloud Scheduler,
    cron jobs, or external webhooks).

Endpoints:
    - POST /: Triggers the YouTube intelligence pipeline. Accepts query parameter `?hours=N`
              or JSON payload `{"hours": N, "dry_run": bool}`.
    - GET /: Health check / manual invocation endpoint supporting `?hours=N`.
"""

from __future__ import annotations

import os
from typing import Any
from flask import Flask, jsonify, request, Response
from src.main import run_pipeline

app: Flask = Flask(__name__)


@app.route("/", methods=["POST", "GET"])
def trigger_digest() -> tuple[Response, int]:
    """
    HTTP trigger route for scheduled daily executions.
    """
    try:
        hours: int = request.args.get("hours", default=24, type=int)
        dry_run: bool = request.args.get("dry_run", default=False, type=lambda v: str(v).lower() in ("true", "1"))

        if request.is_json:
            data = request.get_json(silent=True)
            if data:
                if "hours" in data:
                    hours = int(data["hours"])
                if "dry_run" in data:
                    dry_run = bool(data["dry_run"])

        print(f"[WebService] Trigger received: lookback={hours}h, dry_run={dry_run}")
        result: dict[str, Any] = run_pipeline(
            hours_back=hours,
            dry_run=dry_run,
            trigger_source="cloud_http"
        )

        if result.get("success"):
            return jsonify({
                "status": "success",
                "message": "YouTube Intelligence Digest executed successfully",
                "stats": result.get("stats", {})
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": result.get("error", "Execution failed"),
                "stats": result.get("stats", {})
            }), 500

    except Exception as exc:
        print(f"[WebService] Unhandled error: {exc}")
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
