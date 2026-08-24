@echo off
REM ---------------------------------------------------------------------
REM  Opens ports 3100 and 8100 to the local network.
REM
REM  RIGHT-CLICK THIS FILE AND CHOOSE "Run as administrator".
REM  Only needed once. Without it Windows silently drops connections from
REM  other machines and the page never loads for them.
REM ---------------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   This needs administrator rights.
    echo   Right-click the file and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

REM Scoped to private networks: this should not be reachable from a cafe
REM or hotel network you happen to join later.
netsh advfirewall firewall delete rule name="Job Search Command Center (frontend)" >nul 2>&1
netsh advfirewall firewall delete rule name="Job Search Command Center (backend)" >nul 2>&1
netsh advfirewall firewall add rule name="Job Search Command Center (frontend)" dir=in action=allow protocol=TCP localport=3100 profile=private
netsh advfirewall firewall add rule name="Job Search Command Center (backend)" dir=in action=allow protocol=TCP localport=8100 profile=private

echo.
echo   Ports 3100 and 8100 are now open on private networks.
echo.
pause
