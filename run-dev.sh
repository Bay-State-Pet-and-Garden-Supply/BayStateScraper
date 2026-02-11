#!/bin/bash
# Run scraper daemon in DEVELOPMENT mode (connects to localhost:3000)
# Usage: ./run-dev.sh [--debug]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Bay State Scraper - DEV MODE${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if BayStateApp is running locally
if ! curl -s http://localhost:3000/api/health > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Warning: BayStateApp doesn't appear to be running on localhost:3000${NC}"
    echo ""
    echo "To start the app:"
    echo "  cd ../BayStateApp && npm run dev"
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${YELLOW}⚠ No virtual environment found. Using system Python.${NC}"
fi

# Check if .env.development exists
if [ ! -f ".env.development" ]; then
    echo -e "${YELLOW}⚠ .env.development not found!${NC}"
    echo "Creating from .env..."
    cp .env .env.development
    sed -i.bak 's|https://bay-state-app.vercel.app|http://localhost:3000|g' .env.development
    rm -f .env.development.bak
fi

echo -e "${GREEN}✓ Starting scraper in DEV mode${NC}"
echo -e "${BLUE}  API URL: http://localhost:3000${NC}"
echo ""

# Run daemon with dev environment
exec python daemon.py --env dev "$@"
