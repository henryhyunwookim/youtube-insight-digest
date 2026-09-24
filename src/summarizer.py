"""
YouTube Insight Digest - Gemini Generative AI Summarizer & Intelligence Engine.

Purpose:
    Uses Google Gemini with structured JSON output to analyze video transcripts and metadata,
    generating high-value executive summaries, strategic insights, key moments, and actionable takeaways.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
import google.generativeai as genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL


class VideoSummarizer:
    """
    Coordinates Gemini LLM synthesis and insight generation for YouTube videos.
    """

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key: str | None = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Please ensure 'gemini-api-key' is in Secret Manager, "
                "or pass it to VideoSummarizer(api_key=...)."
            )

        self.model_name: str = model_name or GEMINI_MODEL
        genai.configure(api_key=self.api_key)
        # Using cutting-edge Flash model (default: gemini-3.8-flash) for rapid speed, deep reasoning, and structured JSON output
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={"response_mime_type": "application/json"}
        )

    def summarize_video(self, video_metadata: dict[str, Any], transcript_data: dict[str, Any]) -> dict[str, Any]:
        """
        Synthesizes a YouTube video into a structured intelligence briefing.

        Args:
            video_metadata: dict containing title, author, channel_name, category, url, published_display
            transcript_data: dict containing text, timestamped_text, has_transcript, duration_estimate_minutes

        Returns:
            dict with structured summary and insight fields.
        """
        title = video_metadata.get("title", "")
        author = video_metadata.get("author", "")
        category = video_metadata.get("category", "")
        description = video_metadata.get("description", "")
        has_transcript = transcript_data.get("has_transcript", False)
        duration_mins = transcript_data.get("duration_estimate_minutes", 0.0)

        # Use timestamped text if available, capped at ~150,000 characters for optimal latency
        if has_transcript:
            content_source = "FULL_TRANSCRIPT"
            content_body = transcript_data.get("timestamped_text") or transcript_data.get("text") or ""
            content_body = content_body[:180000]
        else:
            content_source = "VIDEO_DESCRIPTION_ONLY"
            content_body = description[:15000]

        prompt = f"""You are a distinguished Principal AI Architect and Technology Intelligence Analyst.
Analyze the following YouTube video released by '{author}' in the '{category}' domain.
Synthesize its contents into a razor-sharp, dense, high-signal intelligence briefing for an executive technical audience.

### Video Information:
- **Title**: {title}
- **Channel**: {author}
- **Category**: {category}
- **Estimated Duration**: {duration_mins} minutes
- **Content Available**: {content_source}

### Source Material:
{content_body}

### Analysis Requirements (STRICT BREVITY & DENSITY):
CRITICAL: The reader has only 30-45 seconds per video. Eliminate all filler phrases, background fluff, and obvious generic commentary. Prioritize concrete numbers, architectural patterns, benchmarks, and real-world results.

1. **One-Line Hook (`one_line_hook`)**: A single, punchy sentence capturing the primary breakthrough, architecture shift, or metric (max 25 words).
2. **Essential Insights (`key_insights`)**: Exactly 2 to 3 ultra-concise bullets (max 25 words each). Highlight hard data, core architectural decisions, or performance gains.
3. **Actionable Takeaway (`actionable_takeaways`)**: Exactly 1 pragmatic, direct engineering action item or decision rule (max 25 words, e.g., "Adopt X when Y to avoid Z").
4. **Key Moment (`notable_moments`)**: Exactly 1 pivotal timestamped milestone from the video (format: MM:SS or HH:MM:SS with brief context).
   - Identify the single most important breakthrough, demo, benchmark result, or core architectural revelation timestamp from the transcript (or video chapters if available).
   - If transcripts are available, this is MANDATORY (do NOT leave empty). Use the exact timestamp where this key topic begins.
   - If only video description is available and contains timestamps/chapters, use the most relevant chapter. Only return [] if no timestamp information exists in the source material.
5. **Topics & Tags (`tags`)**: 2 to 4 specific technical tags (e.g., ["LangGraph", "Multi-Agent", "Benchmarking"]).

Respond with ONLY a valid JSON object matching this schema:
{{
  "one_line_hook": "string",
  "key_insights": ["bullet 1", "bullet 2"],
  "actionable_takeaways": ["takeaway 1"],
  "notable_moments": [
    {{"timestamp": "MM:SS", "note": "brief context"}}
  ],
  "tags": ["tag1", "tag2", "tag3"]
}}
"""

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = self.model.generate_content(prompt)
                raw_text = response.text.strip()

                # Clean markdown formatting if present
                clean_json = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
                clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()

                result = json.loads(clean_json)

                # Prioritize key_insights; maintain backward-compatible executive_summary fallback
                key_insights = result.get("key_insights") or result.get("executive_summary", [])
                actionable_takeaways = result.get("actionable_takeaways", [])
                notable_moments = result.get("notable_moments", [])
                tags = result.get("tags", [])

                # Normalize notable_moments to standard list of dicts
                normalized_moments: list[dict[str, str]] = []
                if isinstance(notable_moments, list):
                    for item in notable_moments:
                        if isinstance(item, dict):
                            ts_val = str(item.get("timestamp") or "").strip()
                            note_val = str(item.get("note") or "").strip()
                            if ts_val or note_val:
                                normalized_moments.append({"timestamp": ts_val, "note": note_val})
                        elif isinstance(item, str) and item.strip():
                            normalized_moments.append({"timestamp": item.strip(), "note": ""})
                elif isinstance(notable_moments, dict):
                    ts_val = str(notable_moments.get("timestamp") or "").strip()
                    note_val = str(notable_moments.get("note") or "").strip()
                    if ts_val or note_val:
                        normalized_moments.append({"timestamp": ts_val, "note": note_val})

                # If no moment was returned by LLM but transcript was available, extract the first key milestone marker
                if not normalized_moments and has_transcript:
                    ts_matches = re.findall(r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^.\n]+)', content_body)
                    if ts_matches:
                        candidate = ts_matches[1] if len(ts_matches) > 1 else ts_matches[0]
                        normalized_moments.append({
                            "timestamp": candidate[0],
                            "note": candidate[1].strip()[:60]
                        })

                return {
                    "one_line_hook": result.get("one_line_hook", title),
                    "executive_summary": key_insights[:3],
                    "key_insights": key_insights[:3],
                    "actionable_takeaways": actionable_takeaways[:1],
                    "notable_moments": normalized_moments[:1],
                    "tags": tags[:4],
                    "has_transcript": has_transcript,
                    "content_source": content_source
                }

            except Exception as exc:
                print(f"[Summarizer] Attempt {attempt}/{max_retries} failed for '{title}': {exc}")
                if attempt < max_retries:
                    time.sleep(2 * attempt)
                else:
                    # Graceful fallback if LLM synthesis errors out
                    fallback_text = (description[:160] + "...") if len(description) > 160 else (description or "Summary unavailable.")
                    return {
                        "one_line_hook": title,
                        "executive_summary": [fallback_text],
                        "key_insights": [fallback_text],
                        "actionable_takeaways": [f"Watch on YouTube: {video_metadata.get('url')}"],
                        "notable_moments": [],
                        "tags": [category],
                        "has_transcript": has_transcript,
                        "content_source": "FALLBACK"
                    }
        return {}
