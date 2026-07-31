@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
  echo Stopping stale server on port 8000 (PID %%a)...
  taskkill /PID %%a /F >nul 2>&1
)
echo Starting UBETRA at http://127.0.0.1:8000
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
