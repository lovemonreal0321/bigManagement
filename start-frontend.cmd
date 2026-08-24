@echo off
REM ---------------------------------------------------------------------
REM  Job Search Command Center - frontend
REM
REM  Builds on first run (and after a git pull), then serves port 3100 on
REM  every network interface. Leave this window open; closing it stops the
REM  server. Start the backend first.
REM ---------------------------------------------------------------------
setlocal EnableDelayedExpansion
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo.
    echo   Installing dependencies, this takes a minute...
    call npm install || goto :failed
)

REM Turbopack exits without a message on some Windows setups, so this uses the
REM webpack builder. Slower, but it finishes. Delete the .next folder to force
REM a rebuild after pulling changes.
if not exist ".next\BUILD_ID" (
    echo.
    echo   Building... only needed once, and after each git pull.
    call npm run build:webpack || goto :failed
)

echo.
echo   Frontend starting on port 3100. Share one of these with your users:
echo.
REM ipconfig pads its output, so the inner loop trims the leading spaces.
REM On a non-English Windows the label differs - just run ipconfig yourself.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    for /f "tokens=1" %%b in ("%%a") do echo       http://%%b:3100
)
echo.

call npm start

echo.
echo   The frontend stopped.
pause
exit /b 0

:failed
echo.
echo   That step failed - read the message above.
pause
exit /b 1
