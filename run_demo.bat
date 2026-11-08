@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [*] Dang khoi dong Hanoi Bus Live ETA Web App...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_demo.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Da xay ra loi khi chay may chu. Nhan phim bat ky de thoat.
    pause
)
