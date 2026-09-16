"""
Unit and Integration Tests for YouTube Insight Digest.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.youtube_monitor import load_channels, resolve_channel_id
from src.transcript_fetcher import format_seconds_to_timestamp
from src.email_sender import EmailSender


class TestYouTubeInsightDigest(unittest.TestCase):

    def test_load_channels(self):
        channels = load_channels()
        self.assertGreaterEqual(len(channels), 4)
        names = [c["name"] for c in channels]
        self.assertIn("AI Engineer", names)
        self.assertIn("LangChain", names)
        self.assertIn("SuperDataScience", names)
        self.assertIn("AWS Developers", names)

    def test_format_seconds_to_timestamp(self):
        self.assertEqual(format_seconds_to_timestamp(45), "[00:45]")
        self.assertEqual(format_seconds_to_timestamp(125), "[02:05]")
        self.assertEqual(format_seconds_to_timestamp(3665), "[01:01:05]")

    def test_html_digest_generation_empty(self):
        sender = EmailSender.__new__(EmailSender)
        html = sender.build_html_digest([], "September 16, 2026", 4, 24)
        self.assertIn("No New Videos Published", html)
        self.assertIn("YouTube Intelligence Digest", html)

    def test_html_digest_generation_with_content(self):
        sender = EmailSender.__new__(EmailSender)
        mock_digest = [{
            "metadata": {
                "title": "Building Autonomous Multi-Agent Systems",
                "channel_name": "LangChain",
                "channel_badge_color": "#10b981",
                "category": "LLM Agents",
                "url": "https://www.youtube.com/watch?v=sample123",
                "thumbnail_url": "https://i.ytimg.com/vi/sample123/hqdefault.jpg",
                "published_display": "Sep 16, 2026 10:00 UTC"
            },
            "summary": {
                "one_line_hook": "LangGraph enables stateful multi-agent workflows with human-in-the-loop controls.",
                "executive_summary": [
                    "Introduced cyclic graph orchestration for LLM agents.",
                    "Demonstrated checkpoint persistence across long-running sessions."
                ],
                "key_insights": [
                    "Stateful execution dramatically reduces hallucination cascades compared to linear chains."
                ],
                "actionable_takeaways": [
                    "Migrate agent architectures to cyclic graphs when multi-step verification is required."
                ],
                "notable_moments": [
                    {"timestamp": "[03:45]", "note": "Demonstration of time-travel debugging in LangGraph"}
                ],
                "tags": ["LangGraph", "MultiAgent", "Agents"]
            }
        }]

        html = sender.build_html_digest(mock_digest, "September 16, 2026", 4, 24)
        self.assertIn("Building Autonomous Multi-Agent Systems", html)
        self.assertIn("LangChain", html)
        self.assertIn("LangGraph enables stateful multi-agent workflows", html)
        self.assertIn("Executive Summary", html)
        self.assertIn("Strategic Intelligence", html)

    def test_summarizer_model_configuration(self):
        from src.summarizer import VideoSummarizer
        from src.config import GEMINI_MODEL
        summarizer = VideoSummarizer(api_key="mock_key", model_name="gemini-3.8-flash")
        self.assertEqual(summarizer.model_name, "gemini-3.8-flash")
        self.assertEqual(GEMINI_MODEL, "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
