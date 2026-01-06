#!/bin/bash
# Bay State Scraper - Local Runner Setup
# This script is deprecated. Use the interactive wizard instead.

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}This setup script is deprecated.${NC}"
echo -e "${GREEN}Use the interactive installation wizard instead:${NC}"
echo ""
echo "    python install.py"
echo ""

read -p "Run the new wizard now? [Y/n] " -n 1 -r
echo

if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "To run it later: python install.py"
    exit 0
fi

python3 install.py
