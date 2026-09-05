#!/bin/bash
# ============================================
# iLumina Chatbot — Start All Services
# ============================================
# Usage: bash start.sh
#
# This script starts:
# 1. Playwright MCP Server (HTTP on port 9222)
# 2. FastAPI Backend (HTTP on port 8000)
# ============================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${PURPLE}╔══════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║       🚀 iLumina Chatbot            ║${NC}"
echo -e "${PURPLE}║       Starting All Services          ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════╝${NC}"
echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  No .env file found. Copying from .env.example...${NC}"
    cp .env.example .env
    echo -e "${RED}⚠️  Please edit .env and add your GROQ_API_KEY before continuing.${NC}"
    exit 1
fi

# Load environment
source .env 2>/dev/null || true

# Check for required tools
if ! command -v npx &> /dev/null; then
    echo -e "${RED}❌ npx not found. Please install Node.js first.${NC}"
    exit 1
fi

if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo -e "${RED}❌ Python not found. Please install Python 3.10+.${NC}"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Shutting down all services...${NC}"
    kill $PID_PLAYWRIGHT $PID_FASTAPI 2>/dev/null
    wait $PID_PLAYWRIGHT $PID_FASTAPI 2>/dev/null
    echo -e "${GREEN}✅ All services stopped.${NC}"
}
trap cleanup EXIT

# 1. Start Playwright MCP Server
echo -e "${BLUE}[1/3]${NC} Starting Playwright MCP Server on port 9222..."
npx @playwright/mcp@latest --port 9222 --headless &
PID_PLAYWRIGHT=$!
sleep 3
echo -e "${GREEN}  ✅ Playwright MCP running (PID: $PID_PLAYWRIGHT)${NC}"

# 2. Start FastAPI Backend (Context & Action Engine)
echo -e "${BLUE}[2/2]${NC} Starting FastAPI Backend on port 8000..."
$PYTHON -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000 &
PID_FASTAPI=$!
sleep 2
echo -e "${GREEN}  ✅ FastAPI Backend running (PID: $PID_FASTAPI)${NC}"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       ✅ All Services Running!       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  🌐 ${BLUE}Frontend:${NC}    http://localhost:8000"
echo -e "  🤖 ${BLUE}FastAPI:${NC}     http://localhost:8000/docs"
echo -e "  🎭 ${BLUE}Playwright:${NC}  http://localhost:9222/mcp"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services.${NC}"

# Wait for all processes
wait
