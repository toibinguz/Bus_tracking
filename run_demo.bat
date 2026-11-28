@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "Hanoi Bus Live ETA Web App" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_demo.ps1" %*
exit /b 0
