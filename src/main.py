"""
YouTube Insight Digest - Main Orchestration Pipeline.

Purpose:
    Coordinates end-to-end execution:
    1. Validates Google Gmail OAuth credentials.
    2. Scans configured YouTube channels via RSS feeds for new video uploads.
    3. Fetches multi-language video transcripts with timestamp markers.
    4. Synthesizes executive summaries & strategic insights using Google Gemini.
    5. Builds and delivers a responsive HTML email digest to the user's Gmail.
    6. Persists processed video IDs to state.json to prevent duplicate digests.

CLI Usage:
    # Standard daily run (default 24h lookback):
    python -m src.main

    # Test run without sending email (saves digest_preview.html):
    python -m src.main --dry-run

    # Interactive Gmail OAuth login / refresh token setup:
    python -m src.main --auth

    # Custom lookback window (e.g. 48 hours):
    python -m src.main --hours 48

    # Scan a specific channel only:
    python -m src.main --channel @LangChain
"""

from __future__ import annotations

import argparse
import os
import sys
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure UTF-8 output encoding across Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.auth import authenticate_gmail
from src.config import (
    BASE_DIR,
    TIMEZONE,
    DEFAULT_LOOKBACK_HOURS,
    RECIPIENT_EMAIL
)
from src.youtube_monitor import scan_for_new_videos, save_state, load_channels
from src.transcript_fetcher import fetch_video_transcript
from src.summarizer import VideoSummarizer
from src.email_sender import EmailSender


def run_pipeline(
    hours_back: int = DEFAULT_LOOKBACK_HOURS,
    dry_run: bool = False,
    target_channel: str | None = None,
    ignore_state: bool = False
) -> dict[str, Any]:
    """
    Executes the full YouTube monitor, transcript synthesis, and email delivery workflow.

    Returns:
        dict[str, Any]: Execution summary with 'success', 'stats', and 'error'.
    """
    stats: dict[str, Any] = {
        "new_videos_found": 0,
        "digests_generated": 0,
        "email_sent": False,
        "preview_file": None
    }

    try:
        # Step 1: Resolve current operational date & time in target timezone (e.g. Asia/Tokyo)
        try:
            tz = zoneinfo.ZoneInfo(TIMEZONE)
            local_now = datetime.now(tz)
        except Exception:
            local_now = datetime.now()

        date_str = local_now.strftime("%B %d, %Y (%H:%M %Z)")

        print("===========================================================================")
        print(f" YouTube Intelligence Digest Pipeline - {date_str}")
        print(f" Lookback: {hours_back} hours | Mode: {'DRY RUN' if dry_run else 'LIVE'}")
        print("===========================================================================")

        # Step 2: Pre-flight Gmail OAuth credential validation (unless dry-run without credentials)
        email_sender = None
        if not dry_run:
            print("[Step 1/4] Verifying Gmail authentication...")
            creds = authenticate_gmail()
            email_sender = EmailSender(creds=creds)
        else:
            print("[Step 1/4] Dry run mode enabled: Gmail email dispatch will be bypassed.")

        # Step 3: Scan YouTube channels for new video releases
        print(f"[Step 2/4] Scanning YouTube channels for new uploads...")
        channels = load_channels()
        new_videos, state = scan_for_new_videos(
            hours_back=hours_back,
            target_channel_id=target_channel,
            ignore_state=ignore_state
        )
        stats["new_videos_found"] = len(new_videos)

        digests: list[dict[str, Any]] = []

        if not new_videos:
            print("[Step 2/4] No new videos detected within the lookback window.")
        else:
            # Step 4: Extract transcripts and synthesize via Gemini
            print(f"[Step 3/4] Processing {len(new_videos)} video(s) via Gemini...")
            summarizer = VideoSummarizer()

            for idx, vid in enumerate(new_videos, start=1):
                vid_id = vid["video_id"]
                title = vid["title"]
                channel = vid["channel_name"]
                print(f" -> [{idx}/{len(new_videos)}] Extracting transcript: '{title}' ({channel})...")

                transcript_data = fetch_video_transcript(vid_id)
                status_ts = f"Yes ({transcript_data.get('duration_estimate_minutes')}m)" if transcript_data.get("has_transcript") else "No (using metadata)"
                print(f"    Transcript available: {status_ts}")

                print(f"    Synthesizing intelligence briefing with Gemini...")
                summary_data = summarizer.summarize_video(vid, transcript_data)

                digests.append({
                    "metadata": vid,
                    "transcript": transcript_data,
                    "summary": summary_data
                })

        stats["digests_generated"] = len(digests)

        # Step 5: Email delivery or HTML preview generation
        print("[Step 4/4] Finalizing digest delivery...")
        if dry_run:
            # Generate preview HTML file
            sender = email_sender or EmailSender(creds=None) if (BASE_DIR / "credentials.json").exists() else None
            if sender:
                html_content = sender.build_html_digest(digests, date_str, len(channels), hours_back)
            else:
                # Fallback template rendering without auth
                dummy_sender = EmailSender.__new__(EmailSender)
                html_content = dummy_sender.build_html_digest(digests, date_str, len(channels), hours_back)

            preview_path = BASE_DIR / "digest_preview.html"
            with open(preview_path, "w", encoding="utf-8") as pf:
                pf.write(html_content)

            stats["preview_file"] = str(preview_path)
            print(f"[Step 4/4] Dry run successful! HTML preview generated at: {preview_path}")
        else:
            if email_sender:
                print(f"[Step 4/4] Dispatching HTML digest email to {RECIPIENT_EMAIL}...")
                email_sender.send_digest_email(
                    digests=digests,
                    date_str=date_str,
                    monitored_channels_count=len(channels),
                    hours_back=hours_back
                )
                stats["email_sent"] = True

                # Mark processed video IDs in state
                processed = state.setdefault("processed_video_ids", {})
                for v in new_videos:
                    processed[v["video_id"]] = datetime.now(timezone.utc).isoformat()
                save_state(state)
                print(f"[Step 4/4] State saved with {len(new_videos)} processed video ID(s).")

        print("===========================================================================")
        print(" Pipeline execution finished successfully.")
        print("===========================================================================")
        return {"success": True, "stats": stats, "error": None}

    except Exception as exc:
        print(f"\n[Pipeline Error] Execution halted: {exc}", file=sys.stderr)
        return {"success": False, "stats": stats, "error": str(exc)}


def main() -> None:
    """
    CLI entry point parsing command-line flags.
    """
    parser = argparse.ArgumentParser(
        description="YouTube Insight Digest - Automated YouTube Video Intelligence & Email Dispatcher."
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_LOOKBACK_HOURS,
        help=f"Lookback window in hours (default: {DEFAULT_LOOKBACK_HOURS})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate run, generate summaries, and save digest_preview.html without dispatching email."
    )
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Run interactive browser OAuth flow to authenticate Gmail and exit."
    )
    parser.add_argument(
        "--channel",
        type=str,
        default=None,
        help="Specific channel handle or ID to scan (e.g., '@LangChain')."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass state tracking to re-process previously processed videos."
    )

    args = parser.parse_args()

    if args.auth:
        print("[CLI] Initiating interactive Gmail OAuth setup...")
        authenticate_gmail()
        print("[CLI] Authentication complete. You may now run the pipeline.")
        sys.exit(0)

    result = run_pipeline(
        hours_back=args.hours,
        dry_run=args.dry_run,
        target_channel=args.channel,
        ignore_state=args.force
    )

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
