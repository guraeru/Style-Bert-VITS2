@echo off
chcp 65001 > nul
cd /d "%~dp0.."
echo.
echo ========================================
echo   吹き替えバッチ処理を開始します
echo ========================================
echo.
call venv\Scripts\activate.bat
python dubbing_tools\run_batch.py
echo.
pause
