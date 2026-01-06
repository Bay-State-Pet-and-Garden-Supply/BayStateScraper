# Bay State Scraper - Docker Image for Self-Hosted Runners
# Provides consistent Python + Playwright environment for web scraping

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium firefox

# Copy scraper source code
COPY . .

# Set Python path
ENV PYTHONPATH=/app

# Default command runs the job runner
ENTRYPOINT ["python", "run_job.py"]
