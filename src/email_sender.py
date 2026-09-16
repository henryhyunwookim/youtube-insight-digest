"""
YouTube Insight Digest - Email Generation & Delivery Module.

Purpose:
    Constructs a responsive, visually stunning HTML email digest and transmits it
    via the Google Gmail API using authenticated OAuth 2.0 user credentials.
"""

from __future__ import annotations

import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.auth import authenticate_gmail
from src.config import RECIPIENT_EMAIL, RECIPIENT_NAME


class EmailSender:
    """
    Handles HTML template compilation and Gmail API email dispatch.
    """

    def __init__(self, creds: Credentials | None = None) -> None:
        self.creds: Credentials = creds or authenticate_gmail()
        self.service = build("gmail", "v1", credentials=self.creds)

    def build_html_digest(
        self,
        digests: list[dict[str, Any]],
        date_str: str,
        monitored_channels_count: int,
        hours_back: int,
        channel_names: list[str] | None = None
    ) -> str:
        """
        Builds a responsive, modern HTML document for the YouTube intelligence digest email.

        Args:
            digests: List of synthesized video summaries with metadata and insights.
            date_str: Formatted execution date and time string.
            monitored_channels_count: Total number of channels monitored.
            hours_back: Lookback window in hours.
            channel_names: Optional list of channel names for the summary pills bar.

        Returns:
            str: Valid, fully styled HTML email body.
        """
        video_cards_html = ""

        if not digests:
            video_cards_html = f"""
            <div style="background-color: #ffffff; border-radius: 12px; padding: 36px 24px; text-align: center; border: 1px solid #e2e8f0; margin-bottom: 24px;">
                <div style="font-size: 44px; margin-bottom: 12px;">📺</div>
                <h3 style="margin: 0 0 8px 0; color: #0f172a; font-family: 'Plus Jakarta Sans', Arial, sans-serif; font-size: 18px; font-weight: 700;">No New Videos Published</h3>
                <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin: 0; max-width: 460px; margin-left: auto; margin-right: auto;">
                    We scanned all <strong>{monitored_channels_count}</strong> monitored YouTube channels over the past <strong>{hours_back} hours</strong>, but no new videos were uploaded. We will monitor again tomorrow at 12:00 PM JST!
                </p>
            </div>
            """
        else:
            for item in digests:
                meta = item["metadata"]
                summary = item["summary"]

                channel_name = meta.get("channel_name", "YouTube")
                badge_color = meta.get("channel_badge_color", "#4f46e5")
                category = meta.get("category", "AI")
                title = meta.get("title", "")
                url = meta.get("url", "#")
                thumb_url = meta.get("thumbnail_url", "")
                pub_time = meta.get("published_display", "")

                hook = summary.get("one_line_hook", "")
                exec_bullets = summary.get("executive_summary", [])
                insights = summary.get("key_insights", [])
                takeaways = summary.get("actionable_takeaways", [])
                moments = summary.get("notable_moments", [])
                tags = summary.get("tags", [])

                # Executive summary bullets
                exec_html = "".join([f"<li style='margin-bottom: 6px; color: #334155;'>{b}</li>" for b in exec_bullets])

                # Strategic insights
                insights_html = "".join([
                    f"<div style='margin-bottom: 8px; font-size: 13px; line-height: 1.5; color: #1e293b;'>"
                    f"<span style='color: #4338ca; font-weight: 700;'>•</span> {ins}"
                    f"</div>" for ins in insights
                ])

                # Actionable takeaways
                takeaways_html = "".join([
                    f"<div style='margin-bottom: 6px; font-size: 13px; line-height: 1.5; color: #15803d;'>"
                    f"<strong>✓</strong> <span style='color: #1e293b;'>{t}</span>"
                    f"</div>" for t in takeaways
                ])

                # Notable moments
                moments_html = ""
                if moments:
                    moment_items = []
                    for m in moments:
                        ts = m.get("timestamp", "")
                        note = m.get("note", "")
                        moment_items.append(
                            f"<div style='display: inline-block; margin-right: 8px; margin-bottom: 6px; background-color: #f1f5f9; padding: 3px 8px; border-radius: 6px; font-size: 12px; color: #334155;'>"
                            f"<strong style='color: #2563eb;'>{ts}</strong> {note}"
                            f"</div>"
                        )
                    moments_html = f"""
                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #e2e8f0;">
                        <span style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #64748b; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Key Moments & Highlights</span>
                        {"".join(moment_items)}
                    </div>
                    """

                # Tags HTML
                tags_html = " ".join([
                    f"<span style='background: #f1f5f9; color: #475569; padding: 2px 7px; border-radius: 4px; font-size: 11px; margin-right: 4px;'>#{t}</span>"
                    for t in tags
                ])

                video_cards_html += f"""
                <div style="background-color: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 8px rgba(0,0,0,0.04); margin-bottom: 24px; overflow: hidden;">
                    <!-- Card Header -->
                    <div style="padding: 16px 20px 12px 20px; border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <span style="background-color: {badge_color}18; color: {badge_color}; border: 1px solid {badge_color}33; padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; letter-spacing: 0.04em;">
                                {channel_name}
                            </span>
                            <span style="font-size: 12px; color: #94a3b8; margin-left: 8px;">{category}</span>
                        </div>
                        <span style="font-size: 12px; color: #94a3b8;">{pub_time}</span>
                    </div>

                    <!-- Card Body -->
                    <div style="padding: 20px;">
                        <!-- Thumbnail & Title -->
                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                            <tr>
                                <td style="width: 140px; vertical-align: top; padding-right: 16px;">
                                    <a href="{url}" target="_blank" style="text-decoration: none; display: block; border-radius: 8px; overflow: hidden; position: relative; border: 1px solid #e2e8f0;">
                                        <img src="{thumb_url}" alt="Thumbnail" style="width: 140px; height: 78px; object-fit: cover; display: block;" />
                                    </a>
                                </td>
                                <td style="vertical-align: top;">
                                    <h3 style="margin: 0 0 6px 0; font-size: 16px; line-height: 1.35; font-weight: 700; color: #0f172a; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">
                                        <a href="{url}" target="_blank" style="color: #0f172a; text-decoration: none;">{title}</a>
                                    </h3>
                                    <div style="margin-bottom: 4px;">{tags_html}</div>
                                </td>
                            </tr>
                        </table>

                        <!-- One-Line Hook -->
                        {f'<div style="background-color: #f8fafc; border-left: 3px solid #3b82f6; padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 16px; font-size: 13.5px; font-weight: 600; color: #1e293b; line-height: 1.5;">💡 {hook}</div>' if hook else ''}

                        <!-- Executive Summary -->
                        <div style="margin-bottom: 16px;">
                            <span style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #64748b; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Executive Summary</span>
                            <ul style="margin: 0; padding-left: 18px; font-size: 13.5px; line-height: 1.6;">
                                {exec_html}
                            </ul>
                        </div>

                        <!-- Strategic Insights Box -->
                        {f'''
                        <div style="background-color: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 8px; padding: 12px 14px; margin-bottom: 14px;">
                            <span style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #6b21a8; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Strategic Intelligence & Impact</span>
                            {insights_html}
                        </div>
                        ''' if insights else ''}

                        <!-- Actionable Takeaways Box -->
                        {f'''
                        <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 12px 14px; margin-bottom: 14px;">
                            <span style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #166534; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Actionable Practitioner Takeaways</span>
                            {takeaways_html}
                        </div>
                        ''' if takeaways else ''}

                        <!-- Notable Moments -->
                        {moments_html}

                        <!-- Watch Button -->
                        <div style="margin-top: 18px; text-align: right;">
                            <a href="{url}" target="_blank" style="background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 8px 18px; border-radius: 6px; font-size: 12.5px; font-weight: 600; display: inline-block;">
                                ▶ Watch on YouTube
                            </a>
                        </div>
                    </div>
                </div>
                """

        # Render dynamic channel names pill list
        channels_display = ", ".join(channel_names) if channel_names else "AI Engineer, LangChain, SuperDataScience, AWS Developers"

        # Complete Email Template
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Intelligence Digest</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #f8fafc;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}
    </style>
</head>
<body style="margin: 0; padding: 24px 12px; background-color: #f8fafc;">
    <div style="max-width: 650px; margin: 0 auto;">
        <!-- Header Banner -->
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); border-radius: 14px; padding: 28px 24px; color: #ffffff; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td>
                        <span style="background-color: rgba(255,255,255,0.15); color: #e0e7ff; padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;">
                            DAILY INTELLIGENCE BRIEFING
                        </span>
                        <h1 style="margin: 10px 0 4px 0; font-size: 24px; font-weight: 800; letter-spacing: -0.02em;">YouTube Intelligence Digest</h1>
                        <p style="margin: 0; color: #94a3b8; font-size: 13.5px;">{date_str} • Japan Standard Time (12:00 PM JST)</p>
                    </td>
                    <td style="text-align: right; vertical-align: middle;">
                        <div style="background-color: rgba(255,255,255,0.1); border-radius: 10px; padding: 8px 14px; display: inline-block; text-align: center;">
                            <div style="font-size: 20px; font-weight: 800; color: #38bdf8;">{len(digests)}</div>
                            <div style="font-size: 10px; color: #cbd5e1; text-transform: uppercase;">New Videos</div>
                        </div>
                    </td>
                </tr>
            </table>
        </div>

        <!-- Monitored Channels Pills Bar -->
        <div style="background-color: #ffffff; border-radius: 10px; border: 1px solid #e2e8f0; padding: 10px 16px; margin-bottom: 20px; font-size: 12px; color: #64748b;">
            <strong style="color: #0f172a;">Monitored Channels:</strong>
            {channels_display}
        </div>

        <!-- Digest Cards -->
        {video_cards_html}

        <!-- Footer -->
        <div style="text-align: center; padding: 16px; color: #94a3b8; font-size: 12px; line-height: 1.5;">
            <p style="margin: 0 0 6px 0;">Curated automatically by your <strong>YouTube Intelligence Agent</strong> using Google Gemini & Gmail API.</p>
            <p style="margin: 0;">Recipient: <strong>{RECIPIENT_NAME}</strong> ({RECIPIENT_EMAIL})</p>
        </div>
    </div>
</body>
</html>
"""
        return html

    def send_digest_email(
        self,
        digests: list[dict[str, Any]],
        date_str: str,
        monitored_channels_count: int,
        hours_back: int,
        channel_names: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Builds and dispatches the daily YouTube intelligence digest email via Gmail API.

        Args:
            digests: List of synthesized video summaries with metadata and insights.
            date_str: Formatted execution date and time string.
            monitored_channels_count: Total number of channels monitored.
            hours_back: Lookback window in hours.
            channel_names: Optional list of channel names for display in the digest.

        Returns:
            dict[str, Any]: Sent message metadata dictionary from the Gmail API.
        """
        if not RECIPIENT_EMAIL:
            raise ValueError(
                "Recipient email is required to dispatch digest. "
                "Please configure RECIPIENT_EMAIL in your .env file."
            )

        html_body = self.build_html_digest(digests, date_str, monitored_channels_count, hours_back, channel_names=channel_names)

        message = MIMEMultipart("alternative")
        count_tag = f"[{len(digests)} New Videos]" if digests else "[No New Videos]"
        message["Subject"] = f"{count_tag} YouTube Intelligence Digest: AI & Cloud - {date_str}"
        message["To"] = RECIPIENT_EMAIL

        # Plain text fallback
        plain_text = f"YouTube Intelligence Digest - {date_str}\n\n"
        plain_text += f"New Videos: {len(digests)}\n"
        plain_text += f"Monitored Channels: {monitored_channels_count} (Lookback: {hours_back}h)\n\n"
        for item in digests:
            m = item["metadata"]
            s = item["summary"]
            plain_text += f"==========================================================\n"
            plain_text += f"Channel: {m.get('channel_name')} | Category: {m.get('category')}\n"
            plain_text += f"Title: {m.get('title')}\n"
            plain_text += f"Link: {m.get('url')}\n"
            plain_text += f"Hook: {s.get('one_line_hook')}\n"
            plain_text += "Executive Summary:\n"
            for b in s.get("executive_summary", []):
                plain_text += f"  * {b}\n"
            if s.get("key_insights"):
                plain_text += "Strategic Insights:\n"
                for ins in s.get("key_insights", []):
                    plain_text += f"  - {ins}\n"
            if s.get("actionable_takeaways"):
                plain_text += "Actionable Takeaways:\n"
                for t in s.get("actionable_takeaways", []):
                    plain_text += f"  [x] {t}\n"
            plain_text += "\n"

        plain_text += "\nSent automatically by YouTube Insight Digest."

        message.attach(MIMEText(plain_text, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

        raw_email = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        body = {"raw": raw_email}

        try:
            result = self.service.users().messages().send(userId="me", body=body).execute()
            print(f"[Email] YouTube Intelligence digest sent successfully! Message ID: {result.get('id')}")
            return result
        except HttpError as error:
            print(f"[Email] Gmail API dispatch error: {error}")
            raise error
