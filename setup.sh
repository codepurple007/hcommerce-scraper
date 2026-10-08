#!/usr/bin/env bash
# One-shot setup script for the HCommerce scraper
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "==> Installing Python packages..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Installing Playwright Chromium..."
playwright install chromium
playwright install-deps chromium 2>/dev/null || true

echo ""
echo "Setup complete!"
echo ""
echo "To start the server:"
echo "  cd scraper"
echo "  source .venv/bin/activate"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "Then open: http://localhost:8000/docs"
