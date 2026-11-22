@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo    Starting No2SQL - Ask your database any question in clear English
echo    Course Project Demo: SCSE4041 Team Tech Goliaths
echo =====================================================================

cd /d "%~dp0"

:: 1. Check Python installation
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found in your PATH. Please install Python 3.11+.
    pause
    exit /b 1
)

:: 2. Set up virtual environment if not present
if not exist ".venv" (
    echo [1/3] Creating virtual environment (.venv)...
    python -m venv .venv
)

:: 3. Activate venv
call .venv\Scripts\activate.bat

:: 4. Install / verify dependencies
echo [2/3] Verifying dependencies...
python -m pip install -q -r backend\requirements.txt

:: 5. Create .env from .env.example if missing
if not exist ".env" (
    echo [NOTICE] Creating .env from .env.example ...
    copy .env.example .env >nul
    echo.
    echo =====================================================================
    echo [IMPORTANT] Please add your Google Gemini API key to .env:
    echo GEMINI_API_KEY=your_key_here
    echo (Or enter it via the Settings icon inside the web app)
    echo =====================================================================
    echo.
)

:: 6. Launch FastAPI backend + Frontend static server
echo [3/3] Starting No2SQL server at http://localhost:8000 ...
echo [INFO] Swagger documentation available at http://localhost:8000/docs
echo Press Ctrl+C to stop the server.
echo.

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

pause
