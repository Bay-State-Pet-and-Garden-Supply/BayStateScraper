#!/bin/bash
# Setup script for running BayStateScraper locally

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Bay State Scraper - Local Runner Setup ===${NC}"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 could not be found. Please install it."
    exit 1
fi
echo -e "${GREEN}✓ Python 3 found${NC}"

# 2. Check/Instal Dependencies
echo -e "\n${BLUE}Installing dependencies...${NC}"
python3 -m pip install -r scraper_backend/requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# 3. Playwright Browsers
echo -e "\n${BLUE}Installing Playwright browsers...${NC}"
python3 -m playwright install chromium
echo -e "${GREEN}✓ Playwright browsers installed${NC}"

# 4. Environment Configuration
echo -e "\n${BLUE}Configuring environment...${NC}"
ENV_FILE="scraper_backend/.env"

# Try to find secret from BayStateApp if available
APP_ENV_FILE="../BayStateApp/.env.local"
SECRET=""

if [ -f "$APP_ENV_FILE" ]; then
    SECRET=$(grep "SCRAPER_WEBHOOK_SECRET" "$APP_ENV_FILE" | cut -d '=' -f2)
    if [ -n "$SECRET" ]; then
        echo -e "${GREEN}✓ Found webhook secret in BayStateApp${NC}"
    fi
fi

if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Existing .env file found.${NC}"
else
    echo "Creating new .env file..."
    cat > "$ENV_FILE" << EOF
# Local Runner Configuration
SCRAPER_API_URL=http://localhost:3000
SCRAPER_WEBHOOK_SECRET=${SECRET:-replace_with_secret_from_app}
RUNNER_NAME=local-macbook
EOF
    echo -e "${GREEN}✓ Created $ENV_FILE${NC}"
fi

echo -e "\n${BLUE}=== Setup Complete ===${NC}"
echo "To run a job:"
echo "  ./run_local_job.sh --job-id <JOB_ID>"
