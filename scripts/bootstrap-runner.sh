#!/bin/bash
#
# Bay State Scraper - Runner Bootstrap Script
#
# One-command setup for a new scraping runner.
# Downloads, configures, and starts a GitHub Actions self-hosted runner.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/scripts/bootstrap-runner.sh | bash
#
# Or with token directly:
#   curl -fsSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/scripts/bootstrap-runner.sh | bash -s -- --token YOUR_TOKEN
#
# Requirements:
#   - macOS (arm64 or x64) or Linux (x64 or arm64)
#   - Admin access to install Docker if not present
#   - GitHub runner registration token (get from repo settings)
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
REPO_URL="https://github.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper"
RUNNER_DIR="$HOME/actions-runner"
RUNNER_LABELS="self-hosted,docker"
DOCKER_IMAGE="ghcr.io/bay-state-pet-and-garden-supply/baystate-scraper:latest"

# Parse arguments
RUNNER_TOKEN=""
RUNNER_NAME=""
SKIP_DOCKER=""
SKIP_SERVICE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --token)
            RUNNER_TOKEN="$2"
            shift 2
            ;;
        --name)
            RUNNER_NAME="$2"
            shift 2
            ;;
        --skip-docker)
            SKIP_DOCKER="1"
            shift
            ;;
        --skip-service)
            SKIP_SERVICE="1"
            shift
            ;;
        -h|--help)
            echo "Bay State Scraper - Runner Bootstrap"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --token TOKEN     GitHub runner registration token (required)"
            echo "  --name NAME       Runner name (default: hostname)"
            echo "  --skip-docker     Skip Docker installation"
            echo "  --skip-service    Don't install as system service"
            echo "  -h, --help        Show this help"
            echo ""
            echo "Get your token from:"
            echo "  ${REPO_URL}/settings/actions/runners/new"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Banner
echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Bay State Scraper - Runner Bootstrap                 ║"
echo "║                                                              ║"
echo "║  This script will set up a GitHub Actions self-hosted       ║"
echo "║  runner for the Bay State scraping system.                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Detect OS and Architecture
detect_platform() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    
    case "$OS" in
        darwin) OS="osx" ;;
        linux) OS="linux" ;;
        *)
            echo -e "${RED}Unsupported OS: $OS${NC}"
            exit 1
            ;;
    esac
    
    case "$ARCH" in
        x86_64) ARCH="x64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *)
            echo -e "${RED}Unsupported architecture: $ARCH${NC}"
            exit 1
            ;;
    esac
    
    echo -e "${CYAN}Detected: ${OS}-${ARCH}${NC}"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install Docker if not present
install_docker() {
    if [ -n "$SKIP_DOCKER" ]; then
        echo -e "${YELLOW}Skipping Docker installation (--skip-docker)${NC}"
        return
    fi
    
    if command_exists docker; then
        echo -e "${GREEN}✓ Docker already installed${NC}"
        docker --version
        return
    fi
    
    echo -e "${CYAN}Installing Docker...${NC}"
    
    if [ "$OS" = "osx" ]; then
        if command_exists brew; then
            brew install --cask docker
            echo -e "${YELLOW}Please open Docker Desktop to complete installation${NC}"
            echo -e "${YELLOW}Then re-run this script${NC}"
            exit 0
        else
            echo -e "${RED}Please install Docker Desktop from https://docker.com${NC}"
            exit 1
        fi
    elif [ "$OS" = "linux" ]; then
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        echo -e "${YELLOW}You may need to log out and back in for Docker permissions${NC}"
    fi
}

# Verify Docker is running
verify_docker() {
    echo -e "${CYAN}Verifying Docker...${NC}"
    
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}Docker is not running.${NC}"
        if [ "$OS" = "osx" ]; then
            echo -e "${YELLOW}Please open Docker Desktop and try again.${NC}"
        else
            echo -e "${YELLOW}Try: sudo systemctl start docker${NC}"
        fi
        exit 1
    fi
    
    echo -e "${GREEN}✓ Docker is running${NC}"
}

# Get runner token interactively if not provided
get_runner_token() {
    if [ -n "$RUNNER_TOKEN" ]; then
        return
    fi
    
    echo ""
    echo -e "${BOLD}GitHub Runner Token Required${NC}"
    echo ""
    echo "To get your token:"
    echo "  1. Go to: ${CYAN}${REPO_URL}/settings/actions/runners/new${NC}"
    echo "  2. Select your OS ($(uname -s))"
    echo "  3. Copy the token from the configure command"
    echo ""
    read -p "Enter your registration token: " RUNNER_TOKEN
    
    if [ -z "$RUNNER_TOKEN" ]; then
        echo -e "${RED}Token is required${NC}"
        exit 1
    fi
}

# Get runner name
get_runner_name() {
    if [ -z "$RUNNER_NAME" ]; then
        DEFAULT_NAME=$(hostname | cut -d. -f1)
        read -p "Enter runner name [${DEFAULT_NAME}]: " RUNNER_NAME
        RUNNER_NAME=${RUNNER_NAME:-$DEFAULT_NAME}
    fi
    echo -e "${CYAN}Runner name: ${RUNNER_NAME}${NC}"
}

# Get latest runner version
get_runner_version() {
    echo -e "${CYAN}Fetching latest runner version...${NC}"
    RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
    
    if [ -z "$RUNNER_VERSION" ]; then
        # Fallback version
        RUNNER_VERSION="2.321.0"
        echo -e "${YELLOW}Could not fetch latest version, using ${RUNNER_VERSION}${NC}"
    else
        echo -e "${GREEN}Latest version: ${RUNNER_VERSION}${NC}"
    fi
}

# Download and extract runner
download_runner() {
    RUNNER_FILE="actions-runner-${OS}-${ARCH}-${RUNNER_VERSION}.tar.gz"
    RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_FILE}"
    
    echo -e "${CYAN}Creating runner directory: ${RUNNER_DIR}${NC}"
    mkdir -p "$RUNNER_DIR"
    cd "$RUNNER_DIR"
    
    if [ -f ".runner" ]; then
        echo -e "${YELLOW}Runner already configured in ${RUNNER_DIR}${NC}"
        read -p "Remove existing configuration and reinstall? [y/N]: " REINSTALL
        if [ "$REINSTALL" = "y" ] || [ "$REINSTALL" = "Y" ]; then
            # Try to uninstall service first
            if [ -f "./svc.sh" ]; then
                ./svc.sh stop 2>/dev/null || true
                sudo ./svc.sh uninstall 2>/dev/null || true
            fi
            ./config.sh remove --token "$RUNNER_TOKEN" 2>/dev/null || true
            cd ..
            rm -rf "$RUNNER_DIR"
            mkdir -p "$RUNNER_DIR"
            cd "$RUNNER_DIR"
        else
            echo -e "${GREEN}Keeping existing configuration${NC}"
            return
        fi
    fi
    
    echo -e "${CYAN}Downloading runner...${NC}"
    curl -o "$RUNNER_FILE" -L "$RUNNER_URL"
    
    echo -e "${CYAN}Extracting...${NC}"
    tar xzf "$RUNNER_FILE"
    rm "$RUNNER_FILE"
}

# Configure runner
configure_runner() {
    echo -e "${CYAN}Configuring runner...${NC}"
    
    cd "$RUNNER_DIR"
    
    if [ -f ".runner" ]; then
        echo -e "${GREEN}Runner already configured${NC}"
        return
    fi
    
    ./config.sh \
        --url "$REPO_URL" \
        --token "$RUNNER_TOKEN" \
        --name "$RUNNER_NAME" \
        --labels "$RUNNER_LABELS" \
        --unattended \
        --replace
    
    echo -e "${GREEN}✓ Runner configured with labels: ${RUNNER_LABELS}${NC}"
}

# Pull Docker image
pull_docker_image() {
    echo -e "${CYAN}Pulling Docker image...${NC}"
    
    # Try authenticated pull first (for private images)
    if docker pull "$DOCKER_IMAGE" 2>/dev/null; then
        echo -e "${GREEN}✓ Docker image pulled${NC}"
    else
        echo -e "${YELLOW}Could not pull image (may need to build locally or authenticate)${NC}"
        echo -e "${YELLOW}The workflow will build the image on first run${NC}"
    fi
}

# Install as service
install_service() {
    if [ -n "$SKIP_SERVICE" ]; then
        echo -e "${YELLOW}Skipping service installation (--skip-service)${NC}"
        echo ""
        echo "To run manually:"
        echo "  cd $RUNNER_DIR && ./run.sh"
        return
    fi
    
    cd "$RUNNER_DIR"
    
    echo -e "${CYAN}Installing as system service...${NC}"
    
    if [ "$OS" = "osx" ]; then
        ./svc.sh install
        ./svc.sh start
    else
        sudo ./svc.sh install
        sudo ./svc.sh start
    fi
    
    echo -e "${GREEN}✓ Runner service installed and started${NC}"
}

# Print completion message
print_completion() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    Setup Complete!                           ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}Runner Details:${NC}"
    echo "  Name:      $RUNNER_NAME"
    echo "  Labels:    $RUNNER_LABELS"
    echo "  Directory: $RUNNER_DIR"
    echo ""
    echo -e "${BOLD}Verify your runner:${NC}"
    echo "  ${CYAN}${REPO_URL}/settings/actions/runners${NC}"
    echo ""
    echo -e "${BOLD}Service commands:${NC}"
    if [ "$OS" = "osx" ]; then
        echo "  Status:  cd $RUNNER_DIR && ./svc.sh status"
        echo "  Stop:    cd $RUNNER_DIR && ./svc.sh stop"
        echo "  Start:   cd $RUNNER_DIR && ./svc.sh start"
        echo "  Logs:    tail -f ~/Library/Logs/actions.runner.*.log"
    else
        echo "  Status:  sudo systemctl status actions.runner.*"
        echo "  Stop:    sudo systemctl stop actions.runner.*"
        echo "  Start:   sudo systemctl start actions.runner.*"
        echo "  Logs:    journalctl -u actions.runner.* -f"
    fi
    echo ""
    echo -e "${BOLD}Test the runner:${NC}"
    echo "  1. Go to BayStateApp Admin Panel"
    echo "  2. Navigate to Scraper Network"
    echo "  3. Run a test scrape"
    echo ""
}

# Main
main() {
    detect_platform
    install_docker
    verify_docker
    get_runner_token
    get_runner_name
    get_runner_version
    download_runner
    configure_runner
    pull_docker_image
    install_service
    print_completion
}

main
