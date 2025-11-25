# OCR読み上げツール

Style-Bert-VITS2プロジェクト用のOCR読み上げツールです。

## 機能

- **ハイブリッドOCR**: Tesseractで文字種判定 → EasyOCR/Tesseractで抽出
- **自動読み上げ**: Style-Bert-VITS2を使用して抽出したテキストを音声化
- **ホットキー対応**: Shift+F9で画面上の任意の領域をOCR

## 必要な環境

### 1. Tesseract OCR
- インストール先: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- ダウンロード: https://github.com/UB-Mannheim/tesseract/wiki
- 日本語データパック（jpn.traineddata）を含めてインストール

### 2. Pythonパッケージ
venv環境にインストールしてください:
```bash
venv\Scripts\activate
pip install easyocr pytesseract pillow opencv-python pynput pygame
```

### 3. TTSモデル
- `model_assets/ui_speaker/` に以下のファイルが必要:
  - `config.json`
  - `*.safetensors` (モデルファイル)
  - `style_vectors.npy`

## 設定

### settings.ini
`ocr_tool/settings.ini` で各種設定をカスタマイズできます:

```ini
[TTS]
# 使用するモデル（model_assets内のフォルダ名）
model_name = merge_shigureui

[Device]
# 推論デバイス（cuda, cpu, mpsなど）
device = cuda

[Hotkey]
# ホットキーの設定
trigger_key = f9
require_shift = True
require_ctrl = False
require_alt = False
```

**注意**: OCR関連の設定（Tesseract信頼度閾値、画像スケールなど）は研究により最適化された黄金比率のため、変更できません。これらはコード内に固定値として定義されています。

初回起動時にデフォルトの`settings.ini`が自動生成されます。

## 使い方

### 初回セットアップ
```bash
# 1. 必要なパッケージをインストール
setup.bat

# 2. Tesseract OCRをインストール（まだの場合）
# https://github.com/UB-Mannheim/tesseract/wiki からダウンロード
# インストール先: C:\Program Files\Tesseract-OCR\
```

### 起動方法
```bash
# バッチファイルから起動（推奨）
run_ocr.bat

# または直接Pythonで起動
python ocr_tool.py
```

### 操作方法
1. プログラムを起動すると、バックグラウンドで待機状態になります
2. **Shift + F9** を押すと、画面選択モードに入ります
3. マウスで読み取りたい領域をドラッグして選択
4. 自動的にOCRが実行され、結果が読み上げられます
5. 終了する場合は Ctrl+C を押してください

## カスタマイズ

### TTSモデルの変更
`ocr_tool.py` の最後の行で別のモデルを指定できます:
```python
start_hotkey_ocr_app(model_name="他のモデル名")
```

### ホットキーの変更
`KEY_TO_TRIGGER` 変数を変更してください:
```python
KEY_TO_TRIGGER = keyboard.Key.f10  # F10に変更する場合
```

### 正規化辞書の編集
`NORMALIZATION_DICT` を編集して、よくある誤認識を修正できます:
```python
NORMALIZATION_DICT = {
    "誤認識": "正しい文字",
    ...
}
```

## トラブルシューティング

### Tesseractが見つからない
- `TESSERACT_CMD` のパスを確認してください
- 環境変数PATHにTesseractを追加することも可能です

### CUDAエラー
- GPUが使えない場合は自動的にCPUモードになります
- EasyOCRの初期化時に `use_cuda=False` を指定できます

### 読み上げが失敗する
- TTSモデルのパスが正しいか確認してください
- `model_assets/` 内のモデルフォルダ構造を確認してください

### pyopenjtalk関連のエラー
以下のようなエラーが発生した場合:
- `numpy.dtype size changed`
- `module 'pyopenjtalk' has no attribute 'run_frontend'`

**修正スクリプトを実行:**
```bash
fix_numpy.bat
```

または手動で修正:
```bash
venv\Scripts\activate
pip uninstall -y pyopenjtalk pyopenjtalk-dict
pip install --upgrade --force-reinstall numpy
pip install --no-binary :all: --no-cache-dir pyopenjtalk
```

それでも解決しない場合は、特定のバージョンを使用:
```bash
pip uninstall -y pyopenjtalk
pip install pyopenjtalk==0.3.0
```
