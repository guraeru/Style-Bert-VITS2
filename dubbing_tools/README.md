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

[async_io]
# 非同期IO処理（共有ストレージ使用時に推奨）
enable = true
download_pool_size = 3
max_upload_threads = 2
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

- **非同期IO処理**: ダウンロードプールと非同期アップロードで共有ストレージのIOボトルネックを解消
- **進捗保存・再開機能**: 処理が中断しても続きから再開可能（回線切断対応）
- **音声カット禁止ポリシー**: 字幕時間に収まらない場合は話速を自動調整
- **英語→カタカナ変換**: 22万語の辞書による高精度変換
- **イントロ音声保持**: 最初の字幕まで元音声を残す（フェードアウト付き）
- **重複スキップ**: 既存ファイルは自動スキップ
- **文字コード自動検出**: UTF-8, Shift_JIS, CP932 対応

## 🚀 非同期IO処理機能

共有ストレージ（NAS等）を使用する場合、IOがボトルネックになります。
非同期IO処理を有効化すると、以下の最適化により効率的な処理が可能になります：

### 主な最適化

1. **ダウンロードプール**: 処理の数件先までファイルを事前ダウンロード
   - 処理中のIO待ち時間を削減
   - `download_pool_size`で調整可能（デフォルト: 3）

2. **非同期アップロード**: アップロード完了を待たずに次の処理へ
   - バックグラウンドでアップロードを実行
   - `max_upload_threads`で同時アップロード数を調整可能（デフォルト: 2）

3. **自動クリーンアップ**: 一時ファイルを自動削除

### 設定方法

```ini
[async_io]
enable = true               # 非同期IO処理を有効化
download_pool_size = 3      # ダウンロードプールサイズ
max_upload_threads = 2      # 最大アップロードスレッド数
```

### 処理フロー

```
同期処理（従来）:
ダウンロード1 → 処理1 → アップロード1 → ダウンロード2 → 処理2 → アップロード2 → ...

非同期処理（最適化後）:
ダウンロード1,2,3（並行）→ 処理1 → アップロード1（バックグラウンド）
                           ↓
                        処理2 → アップロード2（バックグラウンド）
                           ↓
                        処理3 → ...
```

### 効果

**期待される性能向上:**
- **スループット**: 30-50%向上（共有ストレージ使用時）
- **IO待ち時間**: ダウンロード遅延が隠蔽化され、実質ゼロに
- **処理効率**: 処理とアップロードが並行実行され、待機時間削減

**具体例（100ファイルの場合）:**
- 従来: 各ファイル3分（DL:30秒 + 処理:2分 + UL:30秒）= 合計300分
- 最適化後: 各ファイル約2分（処理時間のみ）= 合計200分
- **削減時間: 約100分（33%短縮）**

※実際の効果はネットワーク速度、ファイルサイズ、処理時間により変動します。



## 🔄 進捗保存・再開機能

バッチ処理中に回線が切れたり、Ctrl+Cで中断しても、次回起動時に続きから再開できます。

### 仕組み

- 処理中の進捗は `output_mp4/.dubbing_progress.json` に自動保存されます
- 各ファイルの処理状態（未処理/処理中/完了/失敗）が記録されます
- 次回起動時、前回の進捗がある場合は再開するか選択できます

### 進捗ファイルの例

```json
{
  "session_id": "20260105_123456",
  "model_name": "jvnv-F1-jp",
  "total_files": 10,
  "completed_count": 5,
  "failed_count": 0,
  "files": [
    {
      "video_path": "input_mp4/動画1.mp4",
      "output_path": "output_mp4/動画1.mp4",
      "status": "completed"
    },
    ...
  ]
}
```

### 起動時の選択肢

```
📂 前回の処理が中断されています
   合計: 10件
   完了: 5件
   残り: 5件

どうしますか？
  [1] 続きから再開する
  [2] 最初からやり直す（進捗をクリア）
  [3] キャンセル
```

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
│   ├── progress_manager.py     # 進捗保存・再開管理
│   └── english_katakana_dict.csv  # 英語→カタカナ辞書
└── README.md
```
