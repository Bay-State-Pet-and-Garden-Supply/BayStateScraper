@echo off
chcp 65001 >nul
title BayState Scraper Runner - thoma-pc
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║           Bay State Scraper Runner - Startup                ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo Starting scraper runner daemon...
echo Runner Name: thoma-pc
echo API URL: https://bay-state-app.vercel.app
echo.
echo Press Ctrl+C to stop the runner
echo.

cd /d "%~dp0"

python daemon.py

if errorlevel 1 (
    echo.
    echo [ERROR] Daemon failed to start. Checking Python...
    python --version
    echo.
    echo Make sure Python is installed and in your PATH.
    pause
)
