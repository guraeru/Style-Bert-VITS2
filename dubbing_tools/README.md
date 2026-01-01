# dubbing_tools - Style-Bert-VITS2 吹き替え自動化ツール

Style-Bert-VITS2 を使用して、字幕ファイル（SRT）から日本語音声を生成し、動画に吹き替えを行うツールです。

## 🚀 クイックスタート

### CLI から実行

```bash
# プロジェクトルートで実行
cd Style-Bert-VITS2

# バッチ処理（config.ini の設定を使用）
python -m dubbing_tools

# モデルを指定してバッチ処理
python -m dubbing_tools batch -m jvnv-F1-jp

# 単一ファイルを処理
python -m dubbing_tools single -v input.mp4 -s input.srt -o output.mp4

# 処理対象ファイル一覧
python -m dubbing_tools list

# 設定確認
python -m dubbing_tools config

# ヘルプ
python -m dubbing_tools --help
```

### Python から使用

```python
from dubbing_tools import DubbingAutomation

# モデル初期化
dubbing = DubbingAutomation(
    model_name="jvnv-F1-jp",  # model_assets/ 内のモデル名
    device="cuda",
)

# 吹き替え動画を作成
dubbing.create_dubbed_video(
    video_path="input.mp4",
    srt_path="input.srt",
    output_path="output.mp4",
    overlay=True,           # 元音声に重ねる
    audio_volume=1.0,       # 生成音声の音量
    original_volume=0.3,    # 元音声の音量
)
```

## 📁 フォルダ構成

```
Style-Bert-VITS2/
├── input_mp4/
│   ├── srt/                    # 字幕ファイル（オプション）
│   │   └── 動画1.srt
│   ├── 講座A/
│   │   ├── 動画1.mp4
│   │   └── 動画1.srt           # 動画と同じフォルダでもOK
│   └── 講座B/
│       └── 動画2.mp4
├── output_mp4/                 # 出力先（自動作成）
│   ├── 講座A/
│   │   └── 動画1.mp4
│   └── 講座B/
│       └── 動画2.mp4
├── model_assets/               # TTSモデル
│   ├── jvnv-F1-jp/
│   └── ...
└── dubbing_tools/              # このツール
```

## ⚙️ 設定ファイル (config.ini)

```ini
[paths]
input_dir = input_mp4
output_dir = output_mp4

[model]
name = jvnv-F1-jp
device = cuda

[audio]
overlay = true
audio_volume = 1.0
original_volume = 0.3

[processing]
skip_existing = true
```

## 📋 CLI コマンド一覧

| コマンド | 説明 |
|---------|------|
| `python -m dubbing_tools` | バッチ処理（デフォルト） |
| `python -m dubbing_tools batch` | バッチ処理 |
| `python -m dubbing_tools single` | 単一ファイル処理 |
| `python -m dubbing_tools list` | 処理対象一覧 |
| `python -m dubbing_tools config` | 設定確認 |

### batch オプション

```
-i, --input         入力フォルダ (default: input_mp4)
-o, --output        出力フォルダ (default: output_mp4)
-m, --model         モデル名
-d, --device        cuda / cpu
--no-overlay        元音声を置き換え
--audio-volume      生成音声の音量 (default: 1.0)
--original-volume   元音声の音量 (default: 0.3)
-f, --force         既存ファイルを上書き
-n, --limit         処理件数制限
```

### single オプション

```
-v, --video         入力動画ファイル (必須)
-s, --srt           字幕ファイル (必須)
-o, --output        出力ファイル (必須)
-m, --model         モデル名
```

## ✨ 機能

- **音声カット禁止ポリシー**: 字幕時間に収まらない場合は話速を自動調整
- **英語→カタカナ変換**: 22万語の辞書による高精度変換
- **イントロ音声保持**: 最初の字幕まで元音声を残す（フェードアウト付き）
- **重複スキップ**: 既存ファイルは自動スキップ
- **文字コード自動検出**: UTF-8, Shift_JIS, CP932 対応

## 📦 ファイル構成

```
dubbing_tools/
├── __init__.py          # パッケージ初期化
├── __main__.py          # CLI エントリーポイント
├── cli.py               # コマンドライン処理
├── batch.py             # バッチ処理
├── config.ini           # 設定ファイル
├── src/
│   ├── dubbing_automation.py   # メインクラス
│   ├── srt_parser.py           # SRT解析
│   ├── audio_generator.py      # 音声生成
│   ├── video_combiner.py       # 動画結合
│   ├── text_preprocessor.py    # テキスト前処理
│   ├── batch_processor.py      # バッチ処理ユーティリティ
│   └── english_katakana_dict.csv  # 英語→カタカナ辞書
└── README.md
```
