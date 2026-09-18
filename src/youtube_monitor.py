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
from src.storage import load_cloud_state, save_cloud_state


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
    Loads previously processed video IDs from cloud state (GCS) to prevent duplicate digests.
    Falls back to local file if present, or temp cache.
    """
    state = load_cloud_state()
    if (not state or not state.get("processed_video_ids")) and STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    state = data
                    save_cloud_state(state)
        except Exception:
            pass

    if "processed_video_ids" not in state:
        state["processed_video_ids"] = {}
    return state


def save_state(state: dict[str, Any]) -> None:
    """
    Saves state including processed video IDs and last run timestamp to Google Cloud Storage.
    Prunes entries older than 30 days to keep the state lightweight.
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

        save_cloud_state(state)
    except Exception as exc:
        print(f"[Monitor] Warning: Could not save cloud state: {exc}")


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


DEFAULT_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def parse_relative_time(time_str: str, now: datetime) -> datetime:
    """
    Parses relative time strings (e.g. '11 hours ago', '1 day ago', '11 時間前')
    into approximate UTC datetimes.
    """
    time_str = time_str.lower().strip()

    # English patterns
    match_en = re.search(r'(\d+)\s*(second|sec|minute|min|hour|hr|day|week|month|year)', time_str)
    if match_en:
        val = int(match_en.group(1))
        unit = match_en.group(2)
        if unit.startswith("sec"):
            return now - timedelta(seconds=val)
        elif unit.startswith("min"):
            return now - timedelta(minutes=val)
        elif unit.startswith("hour") or unit.startswith("hr"):
            return now - timedelta(hours=val)
        elif unit.startswith("day"):
            return now - timedelta(days=val)
        elif unit.startswith("week"):
            return now - timedelta(weeks=val)
        elif unit.startswith("month"):
            return now - timedelta(days=val * 30)
        elif unit.startswith("year"):
            return now - timedelta(days=val * 365)

    # Japanese / Asian patterns
    match_ja = re.search(r'(\d+)\s*(秒|分|時間|日|週間|か月|年)', time_str)
    if match_ja:
        val = int(match_ja.group(1))
        unit = match_ja.group(2)
        if unit == "秒":
            return now - timedelta(seconds=val)
        elif unit == "分":
            return now - timedelta(minutes=val)
        elif unit == "時間":
            return now - timedelta(hours=val)
        elif unit == "日":
            return now - timedelta(days=val)
        elif unit == "週間":
            return now - timedelta(weeks=val)
        elif unit == "か月":
            return now - timedelta(days=val * 30)
        elif unit == "年":
            return now - timedelta(days=val * 365)

    return now


def fetch_channel_rss(channel_id: str, max_retries: int = 3) -> list[dict[str, Any]]:
    """
    Pulls and parses the public RSS XML feed for a YouTube channel ID
    using browser headers and exponential backoff retries.
    """
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(rss_url, headers=DEFAULT_REQUEST_HEADERS, timeout=10)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                if feed.entries:
                    return feed.entries
            elif resp.status_code in (404, 429, 500):
                # Transient YouTube RSS throttling
                pass
        except Exception as exc:
            pass

        if attempt < max_retries - 1:
            time.sleep(1.0 * (attempt + 1))

    return []


def fetch_channel_web_videos(channel_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Fallback mechanism: Scrapes recent video metadata directly from the channel's
    public '/videos' web tab. Highly resilient when YouTube's RSS endpoint is throttled or down.
    """
    handle = channel_entry.get("handle", "").strip()
    ch_id = channel_entry.get("channel_id", "").strip()
    ch_name = channel_entry.get("name", "Unknown Channel")

    if handle:
        clean_handle = handle if handle.startswith("@") else f"@{handle}"
        url = f"https://www.youtube.com/{clean_handle}/videos"
    elif ch_id:
        url = f"https://www.youtube.com/channel/{ch_id}/videos"
    else:
        url = channel_entry.get("url", "").rstrip("/") + "/videos"

    try:
        resp = requests.get(url, headers=DEFAULT_REQUEST_HEADERS, timeout=12)
        if resp.status_code != 200:
            print(f"[Monitor Web Fallback] Warning: {ch_name} returned HTTP {resp.status_code}")
            return []

        html = resp.text
        match = re.search(r'var ytInitialData\s*=\s*({.*?});</script>', html)
        if not match:
            match = re.search(r'window\["ytInitialData"\]\s*=\s*({.*?});</script>', html)
        if not match:
            return []

        data = json.loads(match.group(1))

        # Recursively extract video renderers and lockup view models
        raw_items: list[tuple[str, dict[str, Any]]] = []

        def find_items(obj: Any) -> None:
            if isinstance(obj, dict):
                if "lockupViewModel" in obj:
                    raw_items.append(("lockup", obj["lockupViewModel"]))
                elif "videoRenderer" in obj:
                    raw_items.append(("renderer", obj["videoRenderer"]))
                else:
                    for v in obj.values():
                        find_items(v)
            elif isinstance(obj, list):
                for v in obj:
                    find_items(v)

        find_items(data)
        now_utc = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []

        for item_type, item in raw_items:
            vid_id: str | None = None
            title: str = ""
            time_text: str = ""

            if item_type == "lockup":
                vid_id = item.get("contentId")
                meta = item.get("metadata", {}).get("lockupMetadataViewModel", {})
                title = meta.get("title", {}).get("content", "")
                rows = meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                for row in rows:
                    for part in row.get("metadataParts", []):
                        t = part.get("text", {}).get("content", "")
                        if any(marker in t.lower() for marker in ["ago", "前", "streamed"]):
                            time_text = t
            elif item_type == "renderer":
                vid_id = item.get("videoId")
                title = item.get("title", {}).get("runs", [{}])[0].get("text", "")
                time_text = item.get("publishedTimeText", {}).get("simpleText", "")

            if not vid_id or not title:
                continue

            pub_dt = parse_relative_time(time_text, now_utc) if time_text else now_utc

            results.append({
                "video_id": vid_id,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "author": ch_name,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "channel_badge_color": channel_entry.get("badge_color", "#4f46e5"),
                "category": channel_entry.get("category", "General AI"),
                "published_iso": pub_dt.isoformat(),
                "published_display": pub_dt.strftime("%b %d, %Y %H:%M UTC") if time_text else "Recently uploaded",
                "thumbnail_url": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                "description": ""
            })

        return results
    except Exception as exc:
        print(f"[Monitor Web Fallback] Notice: Web scraping fallback for '{ch_name}' failed: {exc}")
        return []


def scan_for_new_videos(
    hours_back: int = DEFAULT_LOOKBACK_HOURS,
    target_channel_id: str | None = None,
    ignore_state: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Scans all enabled channels for new video uploads within the lookback window.
    Uses public RSS feed with automatic web scraping fallback if YouTube throttles RSS.

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

        # 1. Try public RSS feed first
        entries = fetch_channel_rss(resolved_id)
        if entries:
            print(f"[Monitor] Fetched {len(entries)} recent items via RSS from '{ch_name}' ({ch_handle or resolved_id}).")

            for entry in entries:
                vid_id = getattr(entry, "yt_videoid", None)
                if not vid_id:
                    entry_id = getattr(entry, "id", "")
                    if "yt:video:" in entry_id:
                        vid_id = entry_id.split("yt:video:")[-1]
                    else:
                        link = getattr(entry, "link", "")
                        match = re.search(r"v=([\w-]{11})", link)
                        vid_id = match.group(1) if match else None

                if not vid_id:
                    continue

                if not ignore_state and vid_id in processed_ids:
                    continue

                pub_parsed = getattr(entry, "published_parsed", None)
                if pub_parsed:
                    pub_dt = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
                else:
                    pub_str = getattr(entry, "published", "")
                    try:
                        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except Exception:
                        pub_dt = now_utc

                if pub_dt < cutoff_time:
                    continue

                title = getattr(entry, "title", "Untitled Video")
                link = getattr(entry, "link", f"https://www.youtube.com/watch?v={vid_id}")
                author = getattr(entry, "author", ch_name)

                media_thumbnail = getattr(entry, "media_thumbnail", [])
                if media_thumbnail and isinstance(media_thumbnail, list) and "url" in media_thumbnail[0]:
                    thumbnail_url = media_thumbnail[0]["url"]
                else:
                    thumbnail_url = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

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

        else:
            # 2. Seamless fallback to web scraping if RSS returned 0 or failed
            print(f"[Monitor] RSS feed unavailable/empty for '{ch_name}'. Triggering web channel fallback...")
            web_videos = fetch_channel_web_videos(ch)
            print(f"[Monitor] Web fallback retrieved {len(web_videos)} videos for '{ch_name}'.")

            for v in web_videos:
                vid_id = v["video_id"]
                if not ignore_state and vid_id in processed_ids:
                    continue

                try:
                    pub_dt = datetime.fromisoformat(v["published_iso"])
                except Exception:
                    pub_dt = now_utc

                if pub_dt < cutoff_time:
                    continue

                new_videos.append(v)

    # Sort descending by publication date
    new_videos.sort(key=lambda x: x["published_iso"], reverse=True)
    print(f"[Monitor] Total new videos identified across all channels: {len(new_videos)}")
    return new_videos, state
