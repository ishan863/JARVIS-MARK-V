@echo off
title J.A.R.V.I.S. MARK XL Launcher
color 0B

echo ==========================================================
echo               J.A.R.V.I.S. -- MARK XL LAUNCHER
echo ==========================================================
echo.
echo [1/4] Performing environment sanity checks...

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python and try again.
    pause
    exit /b
)

:: Check if Node/NPM is installed
where npm >nul 2>nul
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: NPM is not installed or not in PATH!
    echo Please install Node.js and try again.
    pause
    exit /b
)

echo       ✓ Python and NPM environments verified.
echo.
echo [2/4] Spinning up FastAPI Headless Assistant Backend...
:: Launch server in a separate, labeled cmd window
start "MARK XL Backend (FastAPI)" cmd /c "color 0A && echo Starting FastAPI Backend on http://127.0.0.1:8000 ... && python server.py"

echo.
echo [3/4] Spinning up Vite React Dashboard Frontend...
:: Launch frontend dev server in a separate, labeled cmd window
start "MARK XL Frontend (Vite)" cmd /c "color 0E && cd frontend && echo Starting Vite React Dashboard on http://localhost:5173 ... && npm run dev"

echo.
echo [4/4] Finalizing startup...
echo       Waiting 4 seconds for servers to initialize...
timeout /t 4 /nobreak >nul

echo       Opening dashboard in your web browser...
start http://localhost:5173

echo.
echo ==========================================================
echo        ✓ SYSTEM ONLINE -- BOTH LAYERS ARE RUNNING!
echo ==========================================================
echo.
echo  * Backend: http://127.0.0.1:8000
echo  * Frontend: http://localhost:5173
echo.
echo  * To terminate both servers, simply close their respectives
echo    command prompt windows ("MARK XL Backend" and "MARK XL Frontend").
echo.
echo ==========================================================
pause
