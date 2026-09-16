# YouTube Insight Digest 📺🤖📬

An automated intelligence system that monitors premier YouTube technical channels (**AI Engineer**, **LangChain**, **SuperDataScience**, **AWS Developers**), extracts video transcripts and metadata, generates executive summaries and strategic insights using **Google Gemini**, and dispatches a responsive HTML digest to your **Gmail** every day at **12:00 PM Japan Standard Time (JST)**.

---

## 🌟 Key Highlights

- **Quota-Free & High Reliability**: Monitors channels via public RSS feeds (`feedparser`) and resolves `@handles` dynamically. Zero YouTube Data API quota consumption.
- **Deep Multilingual Transcripts**: Extracts manual or auto-generated video captions with timestamps via `youtube-transcript-api` across English, Japanese, Korean, and more.
- **Gemini Intelligence Engine**: Generates high-signal briefings:
  - **One-Line Hook**: A razor-sharp 1-sentence synthesis.
  - **Executive Summary**: 3–5 dense bullet points detailing architectures, tools, and results.
  - **Strategic Insights**: Deep analytical takeaways on industry implications and architectural tradeoffs.
  - **Actionable Takeaways**: Concrete steps for engineers and researchers.
  - **Key Moments**: Timestamped milestones (`[MM:SS]`).
- **Responsive Gmail Digest**: Modern typography, channel badge pills, embedded thumbnails, and clean cards designed for both mobile and desktop Gmail clients.
- **Duplicate Prevention**: State tracking via `state.json` guarantees each video is summarized and emailed only once.
- **Production-Ready**: Works seamlessly via local CLI, Windows Task Scheduler, or headless container/webhook triggers.

---

## 📡 Pre-Configured Channels

| Channel | Handle | Domain & Focus |
| :--- | :--- | :--- |
| **AI Engineer** | `@aiDotEngineer` | AI Engineering, Latent Space talks, agent architectures |
| **LangChain** | `@LangChain` | LangGraph, autonomous agents, evaluation frameworks |
| **SuperDataScience** | `@sds-superdatascience` | Data science, machine learning models, industry interviews |
| **AWS Developers** | `@awsdevelopers` | Cloud infrastructure, serverless AI, Amazon Bedrock |

*You can add or customize channels anytime in `channels.json`.*

---

## 📁 Repository Structure

```
youtube-insight-digest/
├── channels.json           # Channel configurations (handles, categories, badges)
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
├── .gitignore              # Ignores credentials, tokens, logs, state
├── run_digest.bat          # Windows one-click execution & task scheduler batch file
├── README.md               # Documentation & operational guide
├── src/
│   ├── __init__.py
│   ├── config.py           # Paths, timezone (Asia/Tokyo), email settings
│   ├── auth.py             # Gmail OAuth 2.0 flow & automatic token refresh
│   ├── youtube_monitor.py  # Handle resolver, RSS feed parser & state manager
│   ├── transcript_fetcher.py # youtube-transcript-api & timestamp formatter
│   ├── summarizer.py       # Google Gemini LLM structured synthesis
│   ├── email_sender.py     # HTML template builder & Gmail API dispatcher
│   ├── main.py             # Main CLI pipeline orchestrator
│   └── app.py              # Flask server for Cloud Run / webhook triggers
└── tests/
    └── test_monitor.py     # Unit test suite
```

---

## 🚀 Quickstart Guide

### 1. Clone or Open the Repository
```bash
cd "c:\Users\hyunwookim\OneDrive - GAFS\ドキュメント\GitHub\youtube-insight-digest"
```

### 2. Install Dependencies
```bash
py -3.11 -m pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
Edit `.env` and fill in:
- `GEMINI_API_KEY`: Your Gemini API key from [Google AI Studio](https://aistudio.google.com/).
- `RECIPIENT_EMAIL`: Your target Gmail address.
- `TIMEZONE`: `Asia/Tokyo` (default).

### 4. Setup Gmail OAuth Credentials
You need a Google OAuth 2.0 client credentials file:
1. Copy your existing `credentials.json` from [AI-news-aggregator-KRJP](file:///c:/Users/hyunwookim/OneDrive%20-%20GAFS/%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88/GitHub/AI-news-aggregator-KRJP) or download an **OAuth 2.0 Client ID (Desktop Application)** from [Google Cloud Console](https://console.cloud.google.com/).
2. Place `credentials.json` in the root folder of this repository.
3. Run the one-time interactive authorization:
   ```bash
   py -3.11 -m src.main --auth
   ```
   *A browser window will open asking you to allow Gmail sending permissions. Once authorized, `token.json` is generated and future runs will authenticate automatically without any user interaction.*

---

## 🧪 Testing & Execution

### Test in Dry-Run Mode (No Email Sent)
Generates summaries and saves `digest_preview.html` in the root folder so you can inspect the rendered design:
```bash
py -3.11 -m src.main --dry-run
```

### Live Run (Scan & Dispatch Email)
```bash
py -3.11 -m src.main
```

### Run for a Specific Channel
```bash
py -3.11 -m src.main --channel @LangChain --dry-run
```

### Custom Lookback Window
```bash
# Check videos published in the past 48 hours
py -3.11 -m src.main --hours 48
```

### Force Re-Processing (Bypass state.json)
```bash
py -3.11 -m src.main --force --dry-run
```

---

## ⏰ Daily Scheduling at 12:00 PM JST

### Method A: Windows Task Scheduler (Recommended for Local Machine)
To trigger the system automatically every day at 12:00 PM Japan Time:

1. Open **Command Prompt / PowerShell** as Administrator or user.
2. Run the following command to register the task:
   ```powershell
   schtasks /Create /TN "YouTubeInsightDigest" /TR "\"c:\Users\hyunwookim\OneDrive - GAFS\ドキュメント\GitHub\youtube-insight-digest\run_digest.bat\"" /SC DAILY /ST 12:00
   ```
3. To verify the scheduled task:
   ```powershell
   schtasks /Query /TN "YouTubeInsightDigest"
   ```

### Method B: Cron / Linux Server (UTC 03:00 = JST 12:00)
```crontab
0 3 * * * cd /path/to/youtube-insight-digest && python -m src.main >> /var/log/youtube_digest.log 2>&1
```

### Method C: Cloud Run + Cloud Scheduler
If deploying to Google Cloud Run in the future:
1. Run `gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 src.app:app`
2. Schedule a Cloud Scheduler job targeting your service URL at `0 12 * * *` with timezone `Asia/Tokyo`.

---

## 🛡️ Git & Security Hygiene
- `.gitignore` is configured to strictly exclude `.env`, `credentials.json`, `token.json`, and `state.json`.
- In accordance with safety policies, no secrets or personal credentials will ever be committed.
