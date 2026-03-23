@echo off
echo ========================================
echo OCR読み上げツール - セットアップ
echo ========================================
echo.

:: ocr_toolフォルダに移動
cd /d "%~dp0"

:: settings.iniからproject_rootを読み取る
setlocal enabledelayedexpansion
set "PROJECT_ROOT="
for /f "usebackq tokens=1,* delims==" %%A in ("settings.ini") do (
    set "KEY=%%A"
    set "VAL=%%B"
    if "!KEY: =!"=="project_root" (
        for /f "tokens=* delims= " %%V in ("!VAL!") do set "PROJECT_ROOT=%%V"
    )
)
endlocal & set "PROJECT_ROOT=%PROJECT_ROOT%"

if "%PROJECT_ROOT%"=="" (
    set "PROJECT_ROOT=%~dp0.."
)

:: venv環境をアクティブ
echo [1/3] venv環境をアクティブ化中...
call "%PROJECT_ROOT%\venv\Scripts\activate.bat"
call venv\Scripts\activate.bat

:: 必要なパッケージをインストール
echo.
echo [2/3] 必要なパッケージをインストール中...
echo - easyocr
echo - pytesseract
echo - pillow
echo - opencv-python
echo - pynput
echo - pygame
echo - scipy
echo.

pip install easyocr pytesseract pillow opencv-python pynput pygame scipy

echo.
echo [3/3] 完了チェック...
python -c "import easyocr, pytesseract, cv2, pynput, pygame, scipy; print('✅ 全てのパッケージが正常にインストールされました！')"

echo.
echo ========================================
echo セットアップ完了
echo ========================================
echo.
echo 次のステップ:
echo 1. Tesseract OCRをインストール
echo    https://github.com/UB-Mannheim/tesseract/wiki
echo    インストール先: C:\Program Files\Tesseract-OCR\
echo.
echo 2. OCRツールを起動
echo    run_ocr.bat をダブルクリック
echo.

pause
