@echo off
chcp 65001 >nul
echo ================================================
echo   QwenAgent - DevOps Tests
echo ================================================
echo.
cd /d %~dp0
python -m tests.devops_tests %*
pause
