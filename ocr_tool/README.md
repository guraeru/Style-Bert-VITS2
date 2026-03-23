# OCR読み上げツール（スタンドアロン版）

Style-Bert-VITS2プロジェクト用のOCR読み上げツールです。  
このフォルダ単体で動作します。

## フォルダ構成

```
ocr_tool/
├── run_ocr.bat              # 起動バッチ
├── setup.bat                # 初回セットアップ
├── ocr_tool.py              # メインスクリプト
├── OCR.py                   # OCRエンジンクラス群
├── text_preprocessor.py     # 英語→カタカナ変換
├── english_katakana_dict.csv # 英語→カタカナ辞書
├── reading_adjustments.csv  # 読み方調整辞書
├── settings.ini             # 設定ファイル
└── README.md
```

## 必要な環境

### 1. Style-Bert-VITS2 本体
- venv環境と `style_bert_vits2` パッケージ、`model_assets/` が必要です
- `settings.ini` の `project_root` にインストール先パスを設定してください

### 2. Tesseract OCR
- インストール先: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- ダウンロード: https://github.com/UB-Mannheim/tesseract/wiki
- 日本語データパック（jpn.traineddata）を含めてインストール

### 2. Pythonパッケージ
Style-Bert-VITS2のvenv環境にインストールしてください:
```bash
setup.bat
```

### 3. TTSモデル
- `<project_root>/model_assets/<model_name>/` に以下のファイルが必要:
  - `config.json`
  - `*.safetensors` (モデルファイル)
  - `style_vectors.npy`

## 設定

### settings.ini
`settings.ini` で各種設定をカスタマイズできます:

```ini
[General]
# Style-Bert-VITS2のルートディレクトリ（絶対パス）
project_root = C:\path\to\Style-Bert-VITS2

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
# 1. settings.ini を編集して project_root を設定
# 2. 必要なパッケージをインストール
setup.bat

# 3. Tesseract OCRをインストール（まだの場合）
# https://github.com/UB-Mannheim/tesseract/wiki からダウンロード
# インストール先: C:\Program Files\Tesseract-OCR\
```

### 起動方法
```bash
# バッチファイルから起動（推奨）
run_ocr.bat

# または直接Pythonで起動（venvをactivate済みの場合）
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
