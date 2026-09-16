"""
YouTube Insight Digest - YouTube Channel Monitor & RSS Ingestion Module.

Purpose:
    Monitors specified YouTube channels, resolves channel handles to RSS feeds,
    and extracts new video uploads with complete metadata (video ID, title, description,
    thumbnail, author, publish date).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any
import feedparser
import requests
from bs4 import BeautifulSoup

from src.config import CHANNELS_FILE, STATE_FILE, DEFAULT_LOOKBACK_HOURS


# Cache resolved channel IDs to avoid repetitive web requests
_RESOLVED_CHANNEL_CACHE: dict[str, str] = {}


def load_channels() -> list[dict[str, Any]]:
    """
    Loads monitored channels configuration from channels.json.
    """
    if not CHANNELS_FILE.exists():
        print(f"[Monitor] Warning: '{CHANNELS_FILE}' not found. Returning empty channel list.")
        return []

    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            channels = json.load(f)
            return [c for c in channels if c.get("enabled", True)]
    except Exception as exc:
        print(f"[Monitor] Error loading channels: {exc}")
        return []


def load_state() -> dict[str, Any]:
    """
    Loads previously processed video IDs from state.json to prevent duplicate digests.
    """
    if not STATE_FILE.exists():
        return {"processed_video_ids": {}, "last_run": None}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "processed_video_ids" not in data:
                data["processed_video_ids"] = {}
            return data
    except Exception as exc:
        print(f"[Monitor] Warning: Could not read state file: {exc}. Starting fresh.")
        return {"processed_video_ids": {}, "last_run": None}


def save_state(state: dict[str, Any]) -> None:
    """
    Saves state including processed video IDs and last run timestamp to state.json.
    Prunes entries older than 30 days to keep the state file lightweight.
    """
    try:
        # Prune old entries (> 30 days)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cleaned_ids = {
            vid: ts for vid, ts in state.get("processed_video_ids", {}).items()
            if isinstance(ts, str) and ts >= cutoff
        }
        state["processed_video_ids"] = cleaned_ids
        state["last_run"] = datetime.now(timezone.utc).isoformat()

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[Monitor] Warning: Could not save state: {exc}")


def resolve_channel_id(channel_entry: dict[str, Any]) -> str | None:
    """
    Resolves the canonical 24-character YouTube Channel ID (e.g., 'UC...') from
    either an explicit channel ID, handle (@name), or channel URL.
    """
    # 1. Direct channel_id if configured
    if "channel_id" in channel_entry and channel_entry["channel_id"]:
        return channel_entry["channel_id"]

    handle = channel_entry.get("handle", "").strip()
    url = channel_entry.get("url", "").strip()

    cache_key = handle or url
    if cache_key in _RESOLVED_CHANNEL_CACHE:
        return _RESOLVED_CHANNEL_CACHE[cache_key]

    target_url = url
    if not target_url and handle:
        clean_handle = handle if handle.startswith("@") else f"@{handle}"
        target_url = f"https://www.youtube.com/{clean_handle}"

    if not target_url:
        return None

    # Check if URL itself is a direct /channel/UC... format
    channel_match = re.search(r"youtube\.com/channel/(UC[\w-]{22})", target_url)
    if channel_match:
        ch_id = channel_match.group(1)
        _RESOLVED_CHANNEL_CACHE[cache_key] = ch_id
        return ch_id

    # Fetch page HTML and inspect RSS link or JSON metadata
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }
        resp = requests.get(target_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            html = resp.text

            # Match <link rel="alternate" type="application/rss+xml" href="...channel_id=UC...">
            rss_match = re.search(r'href="https://www\.youtube\.com/feeds/videos\.xml\?channel_id=(UC[\w-]{22})"', html)
            if rss_match:
                ch_id = rss_match.group(1)
                _RESOLVED_CHANNEL_CACHE[cache_key] = ch_id
                return ch_id

            # Match "channelId":"UC..." or "externalId":"UC..." in YouTube initial data JSON
            id_match = re.search(r'["\'](?:channelId|externalId)["\']:\s*["\'](UC[\w-]{22})["\']', html)
            if id_match:
                ch_id = id_match.group(1)
                _RESOLVED_CHANNEL_CACHE[cache_key] = ch_id
                return ch_id

    except Exception as fetch_err:
        print(f"[Monitor] Warning: Could not resolve channel ID for '{cache_key}': {fetch_err}")

    return None


def fetch_channel_rss(channel_id: str) -> list[dict[str, Any]]:
    """
    Pulls and parses the public RSS XML feed for a YouTube channel ID.
    Returns parsed entry dictionaries.
    """
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        return feed.entries or []
    except Exception as exc:
        print(f"[Monitor] Error fetching RSS feed from {rss_url}: {exc}")
        return []


def scan_for_new_videos(
    hours_back: int = DEFAULT_LOOKBACK_HOURS,
    target_channel_id: str | None = None,
    ignore_state: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Scans all enabled channels for new video uploads within the lookback window.

    Args:
        hours_back: Maximum age of video in hours.
        target_channel_id: If specified, monitors only this channel ID/handle.
        ignore_state: If True, does not filter out already-processed video IDs.

    Returns:
        tuple[list[dict[str, Any]], dict[str, Any]]: List of new video items, and current state.
    """
    channels = load_channels()
    state = load_state()
    processed_ids = state.get("processed_video_ids", {})

    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=hours_back)

    new_videos: list[dict[str, Any]] = []

    for ch in channels:
        ch_name = ch.get("name", "Unknown Channel")
        ch_handle = ch.get("handle", "")

        if target_channel_id and (target_channel_id not in (ch.get("id"), ch_handle, ch.get("channel_id"))):
            continue

        resolved_id = resolve_channel_id(ch)
        if not resolved_id:
            print(f"[Monitor] Skipping '{ch_name}': could not resolve YouTube channel ID.")
            continue

        entries = fetch_channel_rss(resolved_id)
        print(f"[Monitor] Fetched {len(entries)} recent items from '{ch_name}' ({ch_handle or resolved_id}).")

        for entry in entries:
            # Extract video ID
            vid_id = getattr(entry, "yt_videoid", None)
            if not vid_id:
                # Fallback extraction from id: 'yt:video:VIDEO_ID'
                entry_id = getattr(entry, "id", "")
                if "yt:video:" in entry_id:
                    vid_id = entry_id.split("yt:video:")[-1]
                else:
                    link = getattr(entry, "link", "")
                    match = re.search(r"v=([\w-]{11})", link)
                    vid_id = match.group(1) if match else None

            if not vid_id:
                continue

            # Check if video was already processed
            if not ignore_state and vid_id in processed_ids:
                continue

            # Parse publish time
            pub_parsed = getattr(entry, "published_parsed", None)
            if pub_parsed:
                pub_dt = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
            else:
                pub_str = getattr(entry, "published", "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = now_utc

            # Enforce lookback window
            if pub_dt < cutoff_time:
                continue

            # Extract metadata
            title = getattr(entry, "title", "Untitled Video")
            link = getattr(entry, "link", f"https://www.youtube.com/watch?v={vid_id}")
            author = getattr(entry, "author", ch_name)
            
            # Thumbnail extraction
            media_thumbnail = getattr(entry, "media_thumbnail", [])
            if media_thumbnail and isinstance(media_thumbnail, list) and "url" in media_thumbnail[0]:
                thumbnail_url = media_thumbnail[0]["url"]
            else:
                thumbnail_url = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

            # Description extraction
            description = getattr(entry, "summary", "")
            media_desc = getattr(entry, "media_description", None)
            if media_desc:
                description = media_desc

            video_item = {
                "video_id": vid_id,
                "title": title,
                "url": link,
                "author": author,
                "channel_id": resolved_id,
                "channel_name": ch_name,
                "channel_badge_color": ch.get("badge_color", "#4f46e5"),
                "category": ch.get("category", "General AI"),
                "published_iso": pub_dt.isoformat(),
                "published_display": pub_dt.strftime("%b %d, %Y %H:%M UTC"),
                "thumbnail_url": thumbnail_url,
                "description": description.strip() if description else ""
            }

            new_videos.append(video_item)

    # Sort descending by publication date
    new_videos.sort(key=lambda x: x["published_iso"], reverse=True)
    print(f"[Monitor] Total new videos identified across all channels: {len(new_videos)}")
    return new_videos, state
