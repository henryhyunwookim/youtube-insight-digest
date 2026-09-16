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

from src.config import GEMINI_API_KEY


class VideoSummarizer:
    """
    Coordinates Gemini LLM synthesis and insight generation for YouTube videos.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key: str | None = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Please set GEMINI_API_KEY in .env "
                "or pass it to VideoSummarizer(api_key=...)."
            )

        genai.configure(api_key=self.api_key)
        # Using gemini-2.5-flash for rapid speed, deep reasoning, and structured JSON output
        self.model = genai.GenerativeModel(
            "gemini-2.5-flash",
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
Synthesize its contents into an authoritative, dense, high-signal briefing for an executive technical audience.

### Video Information:
- **Title**: {title}
- **Channel**: {author}
- **Category**: {category}
- **Estimated Duration**: {duration_mins} minutes
- **Content Available**: {content_source}

### Source Material:
{content_body}

### Analysis Requirements:
1. **One-Line Hook (`one_line_hook`)**: A razor-sharp, captivating 1-sentence synthesis capturing the primary breakthrough, announcement, or thesis.
2. **Executive Summary (`executive_summary`)**: 3 to 5 dense bullet points summarizing what was presented, key architecture/models/tools involved, and primary findings.
3. **Strategic Insights (`key_insights`)**: 2 to 4 deep analytical perspectives on "Why this matters," architectural tradeoffs, developer ecosystem impact, or industry implications.
4. **Actionable Takeaways (`actionable_takeaways`)**: 2 to 3 concrete engineering or operational action items for AI practitioners.
5. **Notable Moments (`notable_moments`)**: 1 to 3 pivotal quotes or timestamped milestones (format: timestamp + why it is notable). If timestamps are unavailable, provide the quote or topic.
6. **Topics & Tags (`tags`)**: 3 to 5 relevant technical tags (e.g., ["LangGraph", "Multi-Agent", "Evaluation"]).

Respond with ONLY a valid JSON object matching this schema:
{{
  "one_line_hook": "string",
  "executive_summary": ["bullet 1", "bullet 2", "bullet 3"],
  "key_insights": ["insight 1", "insight 2"],
  "actionable_takeaways": ["takeaway 1", "takeaway 2"],
  "notable_moments": [
    {{"timestamp": "[MM:SS]", "note": "description or key quote"}}
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

                # Ensure required fields exist
                return {
                    "one_line_hook": result.get("one_line_hook", title),
                    "executive_summary": result.get("executive_summary", []),
                    "key_insights": result.get("key_insights", []),
                    "actionable_takeaways": result.get("actionable_takeaways", []),
                    "notable_moments": result.get("notable_moments", []),
                    "tags": result.get("tags", []),
                    "has_transcript": has_transcript,
                    "content_source": content_source
                }

            except Exception as exc:
                print(f"[Summarizer] Attempt {attempt}/{max_retries} failed for '{title}': {exc}")
                if attempt < max_retries:
                    time.sleep(2 * attempt)
                else:
                    # Graceful fallback if LLM synthesis errors out
                    return {
                        "one_line_hook": title,
                        "executive_summary": [description[:300] if description else "Summary unavailable."],
                        "key_insights": ["Automated AI synthesis temporarily unavailable."],
                        "actionable_takeaways": [f"Watch the full video at {video_metadata.get('url')}"],
                        "notable_moments": [],
                        "tags": [category],
                        "has_transcript": has_transcript,
                        "content_source": "FALLBACK"
                    }
        return {}
