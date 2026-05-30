@echo off
title J.A.R.V.I.S. MARK XL Launcher
color 0B

echo ==========================================================
echo               J.A.R.V.I.S. -- MARK XL LAUNCHER
echo ==========================================================
echo.
echo [1/2] Performing environment sanity checks...

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python and try again.
    pause
    exit /b
)

echo       ✓ Python environment verified.
echo.
echo [2/2] Launching J.A.R.V.I.S. MARK XL...
start "MARK XL" cmd /c "color 0A && echo Starting MARK XL ... && python main.py"

echo.
echo ==========================================================
echo        ✓ SYSTEM ONLINE -- MARK XL IS RUNNING!
echo ==========================================================
echo.
echo  * To terminate, simply close the MARK XL window.
echo ==========================================================
