@echo off
echo ========================================
echo OCR読み上げツール - セットアップ
echo ========================================
echo.

:: Style-Bert-VITS2のルートディレクトリに移動
cd /d "%~dp0.."

:: venv環境をアクティブ
echo [1/3] venv環境をアクティブ化中...
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
