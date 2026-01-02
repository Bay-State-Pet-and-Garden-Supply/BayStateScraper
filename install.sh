#!/bin/bash
set -e

# Bay State Scraper - Runner Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/OWNER/BayStateScraper/main/install.sh | bash

INSTALL_DIR="${BAYSTATE_INSTALL_DIR:-$HOME/.baystate-runner}"
REPO_URL="https://raw.githubusercontent.com/OWNER/BayStateScraper/main"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}${BOLD}║     Bay State Scraper - Runner Setup     ║${NC}"
    echo -e "${BLUE}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}==>${NC} ${BOLD}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

detect_os() {
    case "$(uname -s)" in
        Darwin*) echo "macos" ;;
        Linux*)  echo "linux" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *) echo "unknown" ;;
    esac
}

install_python_macos() {
    if check_command brew; then
        print_step "Installing Python via Homebrew..."
        brew install python@3.11
    else
        print_error "Homebrew not found. Install Python manually from https://python.org"
        exit 1
    fi
}

install_python_linux() {
    if check_command apt-get; then
        print_step "Installing Python via apt..."
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip python3-venv
    elif check_command dnf; then
        print_step "Installing Python via dnf..."
        sudo dnf install -y python3 python3-pip
    elif check_command yum; then
        print_step "Installing Python via yum..."
        sudo yum install -y python3 python3-pip
    else
        print_error "Could not detect package manager. Install Python manually."
        exit 1
    fi
}

ensure_python() {
    if check_command python3; then
        PYTHON_CMD="python3"
        print_success "Python found: $(python3 --version)"
        return 0
    fi
    
    print_warning "Python not found. Attempting to install..."
    
    OS=$(detect_os)
    case "$OS" in
        macos) install_python_macos ;;
        linux) install_python_linux ;;
        *)
            print_error "Automatic Python installation not supported on $OS"
            print_error "Please install Python 3.9+ manually and re-run this script"
            exit 1
            ;;
    esac
    
    if check_command python3; then
        PYTHON_CMD="python3"
        print_success "Python installed: $(python3 --version)"
    else
        print_error "Python installation failed"
        exit 1
    fi
}

ensure_curl() {
    if ! check_command curl; then
        print_error "curl is required but not installed"
        exit 1
    fi
}

setup_install_dir() {
    print_step "Setting up installation directory..."
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    print_success "Install directory: $INSTALL_DIR"
}

download_runner_files() {
    print_step "Downloading runner files..."
    
    curl -fsSL "$REPO_URL/cli/runner_setup.py" -o runner_setup.py
    curl -fsSL "$REPO_URL/cli/requirements-minimal.txt" -o requirements.txt
    
    print_success "Downloaded runner files"
}

setup_venv() {
    print_step "Creating virtual environment..."
    
    if [ ! -d "venv" ]; then
        $PYTHON_CMD -m venv venv
    fi
    
    source venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    
    print_success "Virtual environment ready"
}

run_setup_wizard() {
    print_step "Starting setup wizard..."
    echo ""
    
    source venv/bin/activate
    $PYTHON_CMD runner_setup.py
}

create_run_script() {
    cat > "$INSTALL_DIR/baystate-runner" << 'SCRIPT'
#!/bin/bash
INSTALL_DIR="$(dirname "$0")"
source "$INSTALL_DIR/venv/bin/activate"
python "$INSTALL_DIR/runner_setup.py" "$@"
SCRIPT
    chmod +x "$INSTALL_DIR/baystate-runner"
    
    if [ -w /usr/local/bin ]; then
        ln -sf "$INSTALL_DIR/baystate-runner" /usr/local/bin/baystate-runner 2>/dev/null || true
    fi
}

main() {
    print_header
    
    ensure_curl
    ensure_python
    setup_install_dir
    download_runner_files
    setup_venv
    create_run_script
    run_setup_wizard
    
    echo ""
    echo -e "${GREEN}${BOLD}Installation complete!${NC}"
    echo ""
    echo "To reconfigure or check status, run:"
    echo "  $INSTALL_DIR/baystate-runner"
    echo ""
}

main "$@"
