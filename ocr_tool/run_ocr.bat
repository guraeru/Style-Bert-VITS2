@echo off
:: すでに最小化モードで再実行されているかチェック
if "%~1" neq "minimized" (
    start "" /min "%~f0" minimized
    exit /b
)

:: ↓ ここから実処理（最小化状態で動く）

:: Style-Bert-VITS2のルートディレクトリに移動
cd /d "%~dp0.."

:: venv環境のPythonを使用
call venv\Scripts\activate.bat

:: OCRツールを実行
python ocr_tool\ocr_tool.py

pause
