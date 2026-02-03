# Bay State Scraper - Docker Image for Self-Hosted Runners
# Provides consistent Python + Playwright environment for web scraping
#
# Usage (daemon mode - recommended):
#   docker run -d --restart unless-stopped \
#     -e SCRAPER_API_URL=https://app.baystatepet.com \
#     -e SCRAPER_API_KEY=bsr_xxxx \
#     baystate-scraper:latest
#
# Usage (single job mode - legacy):
#   docker run --rm \
#     -e SCRAPER_API_URL=https://app.baystatepet.com \
#     -e SCRAPER_API_KEY=bsr_xxxx \
#     baystate-scraper:latest \
#     python runner.py --job-id <uuid>

FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium only - firefox rarely needed)
RUN playwright install chromium

# Copy scraper source code
COPY . .

# Set Python path
ENV PYTHONPATH=/app

# Environment defaults
ENV POLL_INTERVAL=30
ENV MAX_JOBS_BEFORE_RESTART=100

# Default command runs the polling daemon
# Override with: docker run ... python runner.py --job-id <uuid>
ENTRYPOINT ["python", "daemon.py"]
