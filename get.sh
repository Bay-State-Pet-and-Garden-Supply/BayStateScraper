#!/bin/bash
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

IMAGE="ghcr.io/bay-state-pet-and-garden-supply/baystatescraper:latest"
CONTAINER_NAME="baystate-scraper"

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "  ____              ____  _        _        "
    echo " | __ )  __ _ _   _/ ___|| |_ __ _| |_ ___  "
    echo " |  _ \ / _\` | | | \___ \| __/ _\` | __/ _ \ "
    echo " | |_) | (_| | |_| |___) | || (_| | ||  __/ "
    echo " |____/ \__,_|\__, |____/ \__\__,_|\__\___| "
    echo "              |___/                         "
    echo -e "${NC}"
    echo -e "${BOLD}Scraper Runner Installer${NC}"
    echo ""
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is not installed.${NC}"
        echo ""
        echo "Install Docker first:"
        echo "  - Mac: https://docs.docker.com/desktop/install/mac-install/"
        echo "  - Linux: curl -fsSL https://get.docker.com | sh"
        echo "  - Windows: https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo -e "${RED}Error: Docker daemon is not running.${NC}"
        echo "Please start Docker and try again."
        exit 1
    fi
    
    echo -e "${GREEN}✓${NC} Docker is installed and running"
}

get_config() {
    echo ""
    echo -e "${BOLD}Configuration${NC}"
    echo ""
    
    if [ -n "$SCRAPER_API_URL" ]; then
        echo -e "API URL: ${CYAN}$SCRAPER_API_URL${NC} (from environment)"
    else
        echo -e "${YELLOW}Enter your BayStateApp API URL${NC}"
        echo -e "(e.g., https://app.baystatepet.com)"
        read -p "> " SCRAPER_API_URL
        
        if [ -z "$SCRAPER_API_URL" ]; then
            SCRAPER_API_URL="https://app.baystatepet.com"
            echo -e "Using default: ${CYAN}$SCRAPER_API_URL${NC}"
        fi
    fi
    
    if [ -n "$SCRAPER_API_KEY" ]; then
        echo -e "API Key: ${CYAN}${SCRAPER_API_KEY:0:12}...${NC} (from environment)"
    else
        echo ""
        echo -e "${YELLOW}Enter your API Key${NC}"
        echo -e "(Get this from Admin Panel > Scraper Network > Runner Accounts)"
        read -p "> " SCRAPER_API_KEY
        
        if [ -z "$SCRAPER_API_KEY" ]; then
            echo -e "${RED}Error: API Key is required${NC}"
            exit 1
        fi
    fi
    
    if [[ ! "$SCRAPER_API_KEY" == bsr_* ]]; then
        echo -e "${YELLOW}Warning: API key should start with 'bsr_'${NC}"
    fi
    
    if [ -z "$RUNNER_NAME" ]; then
        RUNNER_NAME=$(hostname | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
    fi
    echo ""
    echo -e "Runner Name: ${CYAN}$RUNNER_NAME${NC}"
}

stop_existing() {
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo ""
        echo -e "${YELLOW}Stopping existing container...${NC}"
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Removed old container"
    fi
}

pull_image() {
    echo ""
    echo -e "${BOLD}Pulling latest image...${NC}"
    docker pull "$IMAGE"
    echo -e "${GREEN}✓${NC} Image pulled successfully"
}

start_container() {
    echo ""
    echo -e "${BOLD}Starting scraper daemon...${NC}"
    
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        --init \
        --shm-size=2g \
        -e "SCRAPER_API_URL=$SCRAPER_API_URL" \
        -e "SCRAPER_API_KEY=$SCRAPER_API_KEY" \
        -e "RUNNER_NAME=$RUNNER_NAME" \
        "$IMAGE"
    
    echo -e "${GREEN}✓${NC} Container started"
}

verify_running() {
    echo ""
    sleep 2
    
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${GREEN}${BOLD}Installation complete!${NC}"
        echo ""
        echo -e "Your scraper runner is now running in the background."
        echo ""
        echo -e "${BOLD}Useful commands:${NC}"
        echo -e "  View logs:     ${CYAN}docker logs -f $CONTAINER_NAME${NC}"
        echo -e "  Stop runner:   ${CYAN}docker stop $CONTAINER_NAME${NC}"
        echo -e "  Start runner:  ${CYAN}docker start $CONTAINER_NAME${NC}"
        echo -e "  Update:        ${CYAN}curl -sSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/get.sh | bash${NC}"
        echo ""
    else
        echo -e "${RED}Error: Container failed to start${NC}"
        echo "Check logs with: docker logs $CONTAINER_NAME"
        exit 1
    fi
}

main() {
    print_banner
    check_docker
    get_config
    stop_existing
    pull_image
    start_container
    verify_running
}

main
