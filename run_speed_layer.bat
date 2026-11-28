@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "Hanoi Bus Speed Layer" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_speed_layer.ps1" %*
exit /b 0
