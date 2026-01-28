@echo off
chcp 65001 >nul
echo ================================================
echo   QwenAgent - Installation
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    echo Install: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found

echo Installing dependencies...
pip install flask flask-cors requests -q
echo [OK] Dependencies installed

ollama --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARNING] Ollama not found
    echo Install: https://ollama.ai/download
    echo.
) else (
    echo [OK] Ollama found
    echo Pulling model qwen2.5-coder:3b...
    ollama pull qwen2.5-coder:3b
)

echo.
echo ================================================
echo   Installation complete!
echo ================================================
echo.
echo   Run: start.bat
echo   Open: http://localhost:5002
echo.
pause
