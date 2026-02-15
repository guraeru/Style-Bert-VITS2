# 単一セクション/バッチ処理スクリプト

## 概要

**単一セクション処理** と **バッチ処理** の2つのスクリプトが利用可能で、「単一講座だけを処理したい場合」に対応しました。

## ファイル説明

### 1. `ProcessSection.bat` （推奨）
**単一セクション用** バッチファイル

- ダブルクリックで実行
- セクション選択UI付き
- 1つのセクションのみを処理

**使用例:**
```
ProcessSection.bat
→ セクション選択メニューが表示される
→ セクションを選択して実行
```

### 2. `run_single_section.py`
**単一セクション用** Pythonスクリプト

#### CLIで直接実行:
```bash
python dubbing_tools/run_single_section.py
```
セクション選択UIが表示されます

#### コマンドラインで直接指定:
```bash
python dubbing_tools/run_single_section.py --path "\\192.168.11.6\External_HDD\Coloso\プロVTuber志望者向けバーチャルアバターモデリング＆リギング講座\Section 01. 講座の紹介"
```

#### 短縮オプション:
```bash
python dubbing_tools/run_single_section.py -p "C:\path\to\section"
```

### 3. `run_batch.py` （既存）
**複数セクット用** バッチ処理スクリプト

```bash
# デフォルト設定の入力ディレクトリで全てのセクションを処理
python dubbing_tools/run_batch.py

# カスタムディレクトリで処理
python dubbing_tools/run_batch.py --path "C:\custom\input\directory"
```

## 使い分け

| 用途 | ファイル | 方法 |
|------|--------|------|
| **1つのセクションだけ処理** | `ProcessSection.bat` | ダブルクリック |
| 1つのセクションだけ処理（CLI） | `run_single_section.py` | `python run_single_section.py` |
| 特定パスのセクションを処理 | `run_single_section.py` | `python run_single_section.py --path "..."` |
| 複数セクットを一括処理 | `run_batch.py` | `python run_batch.py` |
| カスタムディレクトリで一括処理 | `run_batch.py` | `python run_batch.py --path "..."` |

## 機能

どちらのスクリプトも以下の機能を備えています：

- ✅ **セクション/ディレクトリ選択UI** - 対話式で処理対象を選択
- ✅ **話者（モデル）選択** - 利用可能なモデルから選択
- ✅ **進捗管理** - 中断後の再開が可能
- ✅ **詳細なログ出力** - 処理状況をリアルタイムで確認
- ✅ **エラーハンドリング** - 失敗ファイルをスキップして続行

## 例：ネットワークドライブから単一セクションを処理

```bash
python dubbing_tools/run_single_section.py -p "\\192.168.11.6\External_HDD\Coloso\プロVTuber志望者向けバーチャルアバターモデリング＆リギング講座\Section 01. 講座の紹介"
```

## トラブルシューティング

### オプション不要の場合
```bash
# UIで選択したい場合は、引数不要
python dubbing_tools/run_single_section.py
```

### 長いパスの場合
```bash
# Windowsのネットワークパスは引用符で囲む
python dubbing_tools/run_single_section.py -p "\\192.168.11.6\External_HDD\..."
```
