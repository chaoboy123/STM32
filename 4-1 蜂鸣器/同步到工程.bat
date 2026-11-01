@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ==========================================
echo   同步本工程所有 .c / .h 到 Keil 工程
echo ==========================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    py "%~dp0sync_keil.py" %*
) else (
    python "%~dp0sync_keil.py" %*
)
echo.
echo 按任意键关闭...
pause >nul
