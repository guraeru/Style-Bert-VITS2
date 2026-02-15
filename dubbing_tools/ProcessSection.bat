@echo off
chcp 65001 > nul
cd /d "%~dp0.."
echo.
echo ========================================
echo   単一セクション吹き替え処理
echo ========================================
echo.
call venv\Scripts\activate.bat
python dubbing_tools\run_single_section.py
echo.
pause
