"""
YouTube Insight Digest - Video Transcript Extraction Module.

Purpose:
    Retrieves video subtitles/captions using youtube-transcript-api across multiple
    languages (English, Japanese, Korean, Chinese, etc.) with automatic fallback to generated transcripts.
    Formats transcripts into compacted paragraphs prefixed by timestamp markers at ~45-60s intervals.
    Filters filler tokens, music/applause markers, and sponsor promotional blocks to optimize token usage.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Any
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound


# Common sponsor keywords, promotion blocks, and filler phrases
_SPONSOR_REGEXES = [
    # Explicit sponsor announcements
    re.compile(r"(?i)\b(?:this video is sponsored by|today'?s video is sponsored by|sponsored by|a huge thanks to|thanks to)\s+[^.\n]+(?:for sponsoring|for supporting|for partnering)[^.\n]*[.]?"),
    re.compile(r"(?i)\b(?:sponsor of today'?s video|today'?s sponsor is|our sponsor today is)\s+[^.\n]+[.]?"),
    # Discount codes / links
    re.compile(r"(?i)\b(?:head to|visit|check out)\s+https?://\S+\s+(?:and use code|to get|for)\s+[^.\n]+[.]?"),
    re.compile(r"(?i)\b(?:use (?:promo )?code|discount code)\s+['\"]?\w+['\"]?\s+(?:at checkout|for \d+%\s*off)[^.\n]*[.]?"),
    re.compile(r"(?i)\b(?:NordVPN|Surfshark|ExpressVPN|Skillshare|Squarespace|Brilliant\.org|BetterHelp|Raycon|Grammarly|Ridge Wallet|Shopify|Morning Brew|Patreon)\b[^.\n]*(?:discount|link in the description|offer|sponsor|deal|30 days|free trial|code)[^.\n]*[.]?"),
    # Call to action / subscribe clutter
    re.compile(r"(?i)\b(?:smash that like button|hit that like button|don'?t forget to (?:like and )?subscribe|hit the (?:notification )?bell|leave a comment down below)[^.\n]*[.]?"),
]

# Non-speech sound cues and repetitive filler words
_NOISE_REGEX = re.compile(r"\[(?:Music|Applause|Laughter|音楽|拍手|歓声|笑い|Lied|Musique|Música)\]", re.IGNORECASE)
_FILLER_REGEX = re.compile(r"\b(?:uh|um|er|ah)\b", re.IGNORECASE)


def parse_iso8601_duration(duration_str: str) -> float:
    """
    Parses an ISO 8601 duration string (e.g. 'PT1H15M33S', 'PT45M', 'PT19S') into float seconds.
    """
    if not duration_str:
        return 0.0
    match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration_str.strip())
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


def get_video_duration_seconds(video_id: str) -> float | None:
    """
    Rapidly determines the duration of a YouTube video in seconds before fetching transcripts.
    Inspects <meta itemprop="duration"> or approxDurationMs from the public video page.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")

            # 1. Check itemprop="duration" content="PT...S"
            m = re.search(r'itemprop="duration"\s+content="([^"]+)"', html)
            if m:
                sec = parse_iso8601_duration(m.group(1))
                if sec > 0:
                    return sec

            # 2. Check "approxDurationMs":"..." in ytInitialPlayerResponse
            m2 = re.search(r'[\'"]approxDurationMs[\'"]:\s*[\'"]?(\d+)[\'"]?', html)
            if m2:
                sec = float(m2.group(1)) / 1000.0
                if sec > 0:
                    return sec
    except Exception:
        pass

    return None


def clean_transcript_text(text: str) -> str:
    """
    Removes filler tokens, noise/applause markers, and recurring sponsor blocks.
    """
    if not text:
        return ""

    # Remove music / applause tags
    cleaned = _NOISE_REGEX.sub(" ", text)

    # Remove recurring sponsor sentences / promotional blocks
    for pattern in _SPONSOR_REGEXES:
        cleaned = pattern.sub(" ", cleaned)

    # Remove filler words
    cleaned = _FILLER_REGEX.sub(" ", cleaned)

    # Collapse repeated whitespace
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned


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
    Compacts transcript into paragraphs with timestamp markers emitted once every 45-60 seconds.

    Returns:
        dict[str, Any] containing:
            - 'has_transcript': bool
            - 'text': str (full continuous text)
            - 'timestamped_text': str (compacted paragraphs with timestamp markers)
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

        # Build clean plain text and compacted timestamped paragraphs (grouped into ~45-60s intervals)
        plain_chunks: list[str] = []
        timestamped_paragraphs: list[str] = []

        current_interval_start: float = 0.0
        current_interval_texts: list[str] = []
        interval_duration: float = 50.0  # 45-60 second window for timestamp markers

        max_time = 0.0
        for chunk in data:
            if isinstance(chunk, dict):
                start_sec = float(chunk.get("start", 0.0))
                chunk_duration = float(chunk.get("duration", 0.0))
                raw_text = str(chunk.get("text", ""))
            else:
                start_sec = float(getattr(chunk, "start", 0.0))
                chunk_duration = float(getattr(chunk, "duration", 0.0))
                raw_text = str(getattr(chunk, "text", ""))

            cleaned_chunk = clean_transcript_text(raw_text).replace("\n", " ").strip()
            if not cleaned_chunk:
                continue

            plain_chunks.append(cleaned_chunk)
            max_time = max(max_time, start_sec + chunk_duration)

            if not current_interval_texts:
                current_interval_start = start_sec
                current_interval_texts.append(cleaned_chunk)
            elif start_sec - current_interval_start >= interval_duration:
                # Flush completed interval as a single timestamped paragraph
                ts_label = format_seconds_to_timestamp(current_interval_start)
                paragraph = " ".join(current_interval_texts)
                timestamped_paragraphs.append(f"{ts_label} {paragraph}")

                # Start next interval
                current_interval_start = start_sec
                current_interval_texts = [cleaned_chunk]
            else:
                current_interval_texts.append(cleaned_chunk)

        # Flush final interval
        if current_interval_texts:
            ts_label = format_seconds_to_timestamp(current_interval_start)
            paragraph = " ".join(current_interval_texts)
            timestamped_paragraphs.append(f"{ts_label} {paragraph}")

        full_plain = " ".join(plain_chunks)
        full_timestamped = "\n\n".join(timestamped_paragraphs)

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
