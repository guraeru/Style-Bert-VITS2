# Style-Bert-VITS2 吹き替え自動化ツール

動画の自動吹き替えを行うアドオンツールです。SRTファイルから字幕を読み取り、TTSで音声を生成し、元の動画と結合します。

## 🚨 重要なポリシー

**音声カットは一切行いません**

このツールは教育コンテンツなどの重要な情報を含む動画を対象としています。受講者が内容を聞き逃すことがないよう、**音声が長すぎる場合でも削除せず、話速を調整して全て再生します**。

- ✅ 話速調整(length_scale)で時間を短縮
- ✅ 許容範囲(デフォルト60秒)内の超過は許可
- ❌ 音声の一部削除は絶対禁止

### 🎵 キュー方式(Queue方式)

**理想と現実の妥協案**

- **理想**: 各音声をSRTの開始時刻通りに再生したい
- **現実**: 話者の速度に完全に合わせるのは現実的ではない
- **妥協案**: キュー方式で遅延再生

音声が字幕時間を超過した場合の動作:

```
字幕A: 00:00 - 00:05 (5秒) ← SRTの開始時刻
  → 音声A: 7秒かかった (2秒超過)
  
字幕B: 00:05 - 00:10 (5秒) ← 本来の開始時刻
  → 音声B: 00:07から開始 (2秒遅延、キュー待ち)
  → 音声カットなし、全て再生
  
字幕C: 00:10 - 00:15 (5秒)
  → 音声C: 状況によりさらに遅延
  → 無音期間があれば相殺される
```

**A音声が長引く → B音声がキューで待機 → 遅延して再生開始**という形で、全ての音声を順次再生します。音声の重複や削除は一切ありません。無音期間で時間を相殺します。

## 機能

1. **SRTファイル解析**: 字幕のタイミングとテキストを抽出
2. **TTS音声生成**: Style-Bert-VITS2で字幕から音声を生成
3. **自動話速調整**: 音声が長すぎる場合は話速を上げて再生成
4. **動画結合**: ffmpegで元の動画に音声を重ねる(または置き換える)

## インストール

### 前提条件

- Python 3.8以上
- Style-Bert-VITS2がインストール済み
- ffmpegがインストール済み

### ffmpegのインストール

Windows:
```bash
# Chocolateyを使用
choco install ffmpeg

# または公式サイトからダウンロード
# https://ffmpeg.org/download.html
```

Linux:
```bash
sudo apt install ffmpeg
```

macOS:
```bash
brew install ffmpeg
```

## 使用方法

### フォルダ構成

```
プロジェクト/
├── input_mp4/
│   ├── srt/
│   │   ├── video1.srt
│   │   └── video2.srt
│   ├── 講座A/
│   │   ├── video1.mp4
│   │   └── video2.mp4
│   └── 講座B/
│       └── video3.mp4
└── output_mp4/
    ├── 講座A/          # input_mp4と同じ構造で出力
    │   ├── video1.mp4
    │   └── video2.mp4
    └── 講座B/
        └── video3.mp4
```

### 基本的な使い方

```python
from dubbing_tools import DubbingAutomation

# モデル設定
dubbing = DubbingAutomation(
    model_name="your_model",
    model_path="model_assets/your_model/model.safetensors",
    config_path="model_assets/your_model/config.json",
    style_vec_path="model_assets/your_model/style_vectors.npy",
    device="cuda",
)

# 吹き替え動画作成
dubbing.create_dubbed_video(
    video_path="input_mp4/講座A/video1.mp4",
    srt_path="input_mp4/srt/video1.srt",
    output_path="output_mp4/講座A/video1.mp4",
)
```

### カスタム設定

```python
dubbing = DubbingAutomation(
    model_name="your_model",
    model_path="model_assets/your_model/model.safetensors",
    config_path="model_assets/your_model/config.json",
    style_vec_path="model_assets/your_model/style_vectors.npy",
    device="cuda",
    tolerance_seconds=30.0,  # 許容超過時間を30秒に設定
    min_length_scale=0.6,    # 最速1.67倍速まで許可
)
```

## パラメータ説明

### DubbingAutomation初期化

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `model_name` | str | - | モデル名 |
| `model_path` | str | - | モデルファイルパス |
| `config_path` | str | - | config.jsonパス |
| `style_vec_path` | str | - | style_vectors.npyパス |
| `device` | str | "cuda" | 使用デバイス("cuda" or "cpu") |
| `ffmpeg_path` | str | "ffmpeg" | ffmpegの実行ファイルパス |
| `tolerance_seconds` | float | 60.0 | 許容超過時間(秒) |
| `min_length_scale` | float | 0.5 | 最小話速(0.5=最速2倍速) |

### create_dubbed_video

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `video_path` | str | - | 元の動画ファイルパス |
| `srt_path` | str | - | SRTファイルパス |
| `output_path` | str | - | 出力動画ファイルパス |
| `temp_audio_path` | str | None | 一時音声ファイルパス |
| `style` | str | "Neutral" | 感情スタイル |
| `style_weight` | float | 1.0 | スタイルの強さ |
| `overlay` | bool | True | 元の音声に重ねる(False=置き換え) |
| `audio_volume` | float | 1.0 | 生成音声の音量 |
| `original_volume` | float | 0.3 | 元の音声の音量 |

## 処理フロー

```
SRTファイル → 解析 → 各字幕ごとにTTS生成 → 話速調整(必要に応じて)
                                                    ↓
                                    キュー方式で順次結合(間に合わなければ遅延再生)
                                                    ↓
                                              1つのWAVファイルに結合
                                                    ↓
                                          全体の時間をチェック
                                                    ↓
                                    許容範囲を超えている? → はい → 全体の話速を調整して再生成
                                                    ↓ いいえ
                                              元の動画と結合
                                                    ↓
                                              吹き替え動画完成

※ 音声の重複や削除は一切なし。超過分は次の音声を遅延(キュー待ち)させて対応。無音期間で相殺。
```

### 話速調整アルゴリズム

1. **個別調整**: 各字幕の音声が字幕時間より長い場合、length_scaleを0.05ずつ下げて再生成
2. **全体調整**: 全ての音声を結合した後、動画時間と比較
3. **許容範囲チェック**: `音声時間 - 動画時間 > tolerance_seconds`なら全体の話速を調整
4. **段階的調整**: length_scaleを0.1ずつ下げて再生成(最大5回試行)

## SRTファイルフォーマット

```srt
1
00:00:01,000 --> 00:00:03,500
これは最初の字幕です。

2
00:00:04,000 --> 00:00:07,200
2番目の字幕です。
複数行も対応しています。

3
00:00:08,000 --> 00:00:10,500
3番目の字幕です。
```

## トラブルシューティング

### ffmpegが見つからない

```python
# ffmpegのフルパスを指定
dubbing = DubbingAutomation(
    ...,
    ffmpeg_path="C:/ffmpeg/bin/ffmpeg.exe",
)
```

### 音声が動画より長すぎる

- `tolerance_seconds`を大きくする(デフォルト60秒)
- `min_length_scale`を小さくして最速を上げる(デフォルト0.5=2倍速)

```python
dubbing = DubbingAutomation(
    ...,
    tolerance_seconds=120.0,  # 2分まで許容
    min_length_scale=0.4,     # 最速2.5倍速
)
```

### CUDAメモリ不足

```python
# CPUモードで実行
dubbing = DubbingAutomation(
    ...,
    device="cpu",
)
```

### SRTファイルの解析エラー

- UTF-8エンコーディングで保存されているか確認
- SRT形式が正しいか確認(番号、タイムスタンプ、テキスト、空行)

## サンプルスクリプト

`examples/dubbing_example.py`に以下のサンプルが含まれています:

1. 基本的な使用例
2. カスタム設定の例
3. バッチ処理の例
4. スタイル違いで複数生成

```bash
python examples/dubbing_example.py
```

## ライセンス

Style-Bert-VITS2のライセンスに従います。

## 注意事項

- 生成された音声の著作権は元のテキストと音声モデルの権利者に帰属します
- 商用利用する場合は関連する権利を確認してください
- ffmpegのライセンス(LGPL/GPL)に注意してください
