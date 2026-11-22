#!/usr/bin/env bash
set -e

echo "====================================================================="
echo "   Starting No2SQL - Ask your database any question in clear English"
echo "   Course Project Demo: SCSE4041 Team Tech Goliaths"
echo "====================================================================="

cd "$(dirname "$0")"

# 1. Check Python
PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    PYTHON_BIN="python"
fi

if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "[ERROR] Python 3 was not found. Please install Python 3.11+."
    exit 1
fi

# 2. Virtual Environment
if [ ! -d ".venv" ]; then
    echo "[1/3] Creating virtual environment (.venv)..."
    "$PYTHON_BIN" -m venv .venv
fi

# 3. Activate
source .venv/bin/activate

# 4. Install dependencies
echo "[2/3] Verifying dependencies..."
pip install -q -r backend/requirements.txt

# 5. Create .env from .env.example if missing
if [ ! -f ".env" ]; then
    echo "[NOTICE] Creating .env from .env.example ..."
    cp .env.example .env
    echo ""
    echo "====================================================================="
    echo "[IMPORTANT] Please add your Google Gemini API key to .env:"
    echo "GEMINI_API_KEY=your_key_here"
    echo "(Or enter it via the Settings icon inside the web app)"
    echo "====================================================================="
    echo ""
fi

# 6. Launch server
echo "[3/3] Starting No2SQL server at http://localhost:8000 ..."
echo "[INFO] Swagger documentation available at http://localhost:8000/docs"
echo "Press Ctrl+C to stop the server."
echo ""

exec python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
