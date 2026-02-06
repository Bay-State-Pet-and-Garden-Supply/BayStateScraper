#!/bin/bash
# Bay State Scraper - Runner Launch Script
# Starts the polling daemon

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Set environment variables from .env
export $(grep -v '^#' .env | xargs)

# Run daemon
exec python daemon.py "$@"
