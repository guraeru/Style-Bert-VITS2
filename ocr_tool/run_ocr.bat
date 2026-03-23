@echo off
:: すでに最小化モードで再実行されているかチェック
if "%~1" neq "minimized" (
    start "" /min "%~f0" minimized
    exit /b
)

:: ↓ ここから実処理（最小化状態で動く）

:: ocr_toolフォルダ自体に移動
cd /d "%~dp0"

:: settings.iniからproject_rootを読み取る
setlocal enabledelayedexpansion
set "PROJECT_ROOT="
for /f "usebackq tokens=1,* delims==" %%A in ("settings.ini") do (
    set "KEY=%%A"
    set "VAL=%%B"
    :: 前後の空白を除去してproject_rootを取得
    if "!KEY: =!"=="project_root" (
        for /f "tokens=* delims= " %%V in ("!VAL!") do set "PROJECT_ROOT=%%V"
    )
)
endlocal & set "PROJECT_ROOT=%PROJECT_ROOT%"

:: project_rootが取得できなかった場合は親ディレクトリをフォールバック
if "%PROJECT_ROOT%"=="" (
    set "PROJECT_ROOT=%~dp0.."
)

:: venv環境のPythonを使用
call "%PROJECT_ROOT%\venv\Scripts\activate.bat"

:: OCRツールを実行（ocr_toolフォルダ内から直接）
python ocr_tool.py

pause
