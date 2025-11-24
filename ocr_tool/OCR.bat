@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo   OCR Tool Launcher
echo ========================================
echo.

REM Python実行ファイルを検索
set PYTHON_CMD=python

REM Pythonが見つからない場合は終了
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Pythonが見つかりません。
    echo    Pythonをインストールしてパスを通してください。
    pause
    exit /b 1
)

echo ✅ Python検出: %PYTHON_CMD%
echo.
echo OCRツールを起動中...
echo Shift+F9 でOCR実行、Ctrl+C で終了
echo.

REM OCRツールを実行
%PYTHON_CMD% ocr_tool.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ エラーが発生しました。
    pause
)
