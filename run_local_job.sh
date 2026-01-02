#!/bin/bash
# Wrapper to run a scrape job locally
# Usage: ./run_local_job.sh --job-id <uuid> [--debug]

set -e

# Load environment variables
if [ -f scraper_backend/.env ]; then
    export $(grep -v '^#' scraper_backend/.env | xargs)
fi

# Determine python command
PYTHON_CMD="python3"
if command -v python &> /dev/null && python --version | grep -q "Python 3"; then
    PYTHON_CMD="python"
fi

# Run the runner module
# We add the current directory to PYTHONPATH so imports work correctly
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "Running with API URL: $SCRAPER_API_URL"
$PYTHON_CMD -m scraper_backend.runner "$@"
