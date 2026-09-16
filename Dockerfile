FROM python:3.11-slim

# Ensure standard output and error are streamed immediately to Cloud Logging
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system and Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and channel configuration
COPY src/ ./src/
COPY channels.json ./

# Copy local credentials, token, and environment configuration
COPY credentials.json* token.json* .env* ./

# Add /app to PYTHONPATH
ENV PYTHONPATH=/app

# Run the Flask web service on container startup using Gunicorn
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.app:app"]
