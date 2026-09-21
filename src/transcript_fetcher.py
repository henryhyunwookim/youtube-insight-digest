"""
YouTube Insight Digest - Video Transcript Extraction Module.

Purpose:
    Retrieves video subtitles/captions using youtube-transcript-api across multiple
    languages (English, Japanese, Korean, Chinese, etc.) with automatic fallback to generated transcripts.
    Formats transcripts with timestamp markers for accurate LLM citation.
"""

from __future__ import annotations

from typing import Any
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound


def format_seconds_to_timestamp(seconds: float) -> str:
    """
    Converts float seconds into [MM:SS] or [HH:MM:SS] timestamp string.
    """
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def fetch_video_transcript(video_id: str) -> dict[str, Any]:
    """
    Fetches the transcript for a given YouTube video ID.

    Returns:
        dict[str, Any] containing:
            - 'has_transcript': bool
            - 'text': str (full continuous text)
            - 'timestamped_text': str (transcript lines prefixed with timestamps)
            - 'language': str
            - 'is_generated': bool
            - 'duration_estimate_minutes': float
    """
    try:
        # Support both new v1.2+ instantiated API and legacy static API
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
        except TypeError:
            transcript_list = getattr(YouTubeTranscriptApi, "list_transcripts")(video_id)

        # Attempt to find manual transcript first, then fallback to auto-generated
        preferred_languages = ["en", "en-US", "en-GB", "ja", "ko", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "zh-HK", "zh"]
        transcript = None

        try:
            transcript = transcript_list.find_manually_created_transcript(preferred_languages)
        except Exception:
            pass

        if not transcript:
            try:
                transcript = transcript_list.find_generated_transcript(preferred_languages)
            except Exception:
                pass

        # Fallback to any transcript available if preferred not found
        if not transcript:
            for t in transcript_list:
                transcript = t
                break

        if not transcript:
            return {
                "has_transcript": False,
                "text": "",
                "timestamped_text": "",
                "language": "unknown",
                "is_generated": False,
                "duration_estimate_minutes": 0.0
            }

        data = transcript.fetch()
        if not data:
            return {
                "has_transcript": False,
                "text": "",
                "timestamped_text": "",
                "language": getattr(transcript, "language_code", "unknown"),
                "is_generated": getattr(transcript, "is_generated", False),
                "duration_estimate_minutes": 0.0
            }

        # Build clean plain text and timestamped text
        plain_lines: list[str] = []
        timestamped_lines: list[str] = []
        last_timestamp_sec: float = -60.0

        max_time = 0.0
        for chunk in data:
            # Handle both dictionary chunks and FetchedTranscriptSnippet objects
            if isinstance(chunk, dict):
                start_sec = chunk.get("start", 0.0)
                raw_text = chunk.get("text", "")
            else:
                start_sec = getattr(chunk, "start", 0.0)
                raw_text = getattr(chunk, "text", "")

            text = raw_text.strip().replace("\n", " ")
            if not text:
                continue

            plain_lines.append(text)
            max_time = max(max_time, start_sec)

            # Insert timestamp markers periodically (~45s intervals)
            if start_sec - last_timestamp_sec >= 45.0:
                ts_label = format_seconds_to_timestamp(start_sec)
                timestamped_lines.append(f"{ts_label} {text}")
                last_timestamp_sec = start_sec
            else:
                timestamped_lines.append(text)

        full_plain = " ".join(plain_lines)
        full_timestamped = "\n".join(timestamped_lines)

        return {
            "has_transcript": True,
            "text": full_plain,
            "timestamped_text": full_timestamped,
            "language": getattr(transcript, "language_code", "unknown"),
            "is_generated": getattr(transcript, "is_generated", False),
            "duration_estimate_minutes": round(max_time / 60.0, 1)
        }

    except (TranscriptsDisabled, NoTranscriptFound):
        print(f"[Transcript] No subtitles/transcripts available for video {video_id}.")
    except Exception as exc:
        print(f"[Transcript] Notice: Could not extract transcript for video {video_id}: {exc}")

    return {
        "has_transcript": False,
        "text": "",
        "timestamped_text": "",
        "language": "none",
        "is_generated": False,
        "duration_estimate_minutes": 0.0
    }
