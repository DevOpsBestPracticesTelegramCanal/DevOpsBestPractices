@echo off
chcp 65001 >nul
echo ================================================
echo   QwenAgent - Autonomous Code Agent
echo ================================================
echo.
cd /d %~dp0
python server.py
pause
