@echo off
REM ---------------------------------------------------------------------
REM  Job Search Command Center - backend
REM
REM  Serves the API on port 8100, on every network interface, so other
REM  machines on the network can reach it. Leave this window open; closing
REM  it stops the server.
REM ---------------------------------------------------------------------
setlocal EnableDelayedExpansion
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   No virtual environment found in backend\.venv
    echo.
    echo   Create one first:
    echo       cd backend
    echo       python -m venv .venv
    echo       .venv\Scripts\pip install -r requirements.txt
    echo       copy .env.example .env
    echo.
    pause
    exit /b 1
)

echo.
echo   Backend starting on port 8100, reachable from this network.
echo   API docs: http://localhost:8100/docs
echo.

REM --host 0.0.0.0 is what makes it reachable from other machines. Bound to
REM 127.0.0.1 it would answer only on this one.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8100

echo.
echo   The backend stopped.
pause
