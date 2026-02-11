#!/bin/bash
# Run scraper daemon in PRODUCTION mode (connects to Vercel)
# Usage: ./run-prod.sh [--debug]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Bay State Scraper - PRODUCTION MODE${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${YELLOW}⚠ No virtual environment found. Using system Python.${NC}"
fi

# Verify .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}✗ .env file not found!${NC}"
    echo "Please create a .env file with your production API credentials."
    exit 1
fi

# Extract API URL from .env
API_URL=$(grep "^SCRAPER_API_URL=" .env | cut -d '=' -f2 | tr -d '"' || echo "")
if [ -z "$API_URL" ]; then
    API_URL="https://bay-state-app.vercel.app"
fi

echo -e "${GREEN}✓ Starting scraper in PRODUCTION mode${NC}"
echo -e "${BLUE}  API URL: $API_URL${NC}"
echo ""

# Run daemon with prod environment (default)
exec python daemon.py --env prod "$@"
