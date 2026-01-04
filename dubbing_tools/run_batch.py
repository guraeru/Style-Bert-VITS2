"""
バッチ吹き替え処理 - メインエントリーポイント

使用方法:
    python dubbing_tools/run_batch.py
    
話者を選択式で選んで一括処理を開始します。
"""

import sys
import re
import configparser
import os
from pathlib import Path
from loguru import logger

# プロジェクトルートを自動検出
PROJECT_ROOT = Path(__file__).parent.parent
DUBBING_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# ===== ロギング設定 =====
logger.remove()
logger.add(
    sys.stderr,
    format="<level>{time:HH:mm:ss}</level> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)


def is_continuation(filename: str) -> bool:
    """
    ファイル名が続編（xx-2以上）かどうかを判定
    
    続編ファイル（冒頭音声なし）:
      - 01-2, 02-2, 1-2, 2-2, 1-3, 2-10 など
      
    開始ファイル（冒頭音声あり）:
      - 001, 01-1, 1, 1-1, 2-1 など
      
    Args:
        filename: ファイル名（拡張子なし）
        
    Returns:
        続編（xx-2以上）ならTrue、それ以外はFalse
    """
    # ファイル名の先頭部分を抽出（最初の数字と記号まで）
    match = re.match(r'^(\d+)(?:-(\d+))?', filename)
    if not match:
        # パターンにマッチしない場合は冒頭音声を入れる（続編ではない）
        return False
    
    part_num = int(match.group(2)) if match.group(2) else None
    
    # パターン判定
    # 1. 単独の数字の場合（1, 2, 001等）→ 続編ではない
    if part_num is None:
        return False
    
    # 2. "N-1"パターン（セクションNの第1部）→ 続編ではない
    if part_num == 1:
        return False
    
    # 3. N-2, N-3等は続編なのでTrue
    return True


def get_available_models():
    """利用可能なモデル一覧を取得"""
    model_dir = PROJECT_ROOT / "model_assets"
    if not model_dir.exists():
        return []
    
    models = []
    for d in model_dir.iterdir():
        if d.is_dir() and not d.name.startswith('.'):
            # .safetensorsファイルがあるかチェック
            safetensors = list(d.glob("*.safetensors"))
            if safetensors:
                models.append(d.name)
    return sorted(models)


def select_model(models: list) -> str:
    """対話式でモデルを選択"""
    print("\n" + "=" * 50)
    print("🎤 話者（モデル）を選択してください")
    print("=" * 50)
    
    for i, model in enumerate(models, 1):
        print(f"  [{i}] {model}")
    
    print()
    
    while True:
        try:
            choice = input("番号を入力 > ").strip()
            if not choice:
                continue
            
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx]
                print(f"\n✅ 選択: {selected}\n")
                return selected
            else:
                print("❌ 無効な番号です。もう一度入力してください。")
        except ValueError:
            print("❌ 数字を入力してください。")
        except KeyboardInterrupt:
            print("\n\nキャンセルしました。")
            sys.exit(0)


def load_config():
    """config.ini から設定を読み込む"""
    config_path = DUBBING_TOOLS_DIR / "config.ini"
    
    # デフォルト設定
    settings = {
        "input_dir": "input_mp4",
        "output_dir": "output_mp4",
        "model_name": "jvnv-F1-jp",
        "device": "cuda",
        "overlay": True,
        "audio_volume": 1.0,
        "original_volume": 0.3,
        "skip_existing": True,
    }
    
    if not config_path.exists():
        return settings
    
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    
    # [paths]
    if config.has_section("paths"):
        settings["input_dir"] = config.get("paths", "input_dir", fallback=settings["input_dir"])
        settings["output_dir"] = config.get("paths", "output_dir", fallback=settings["output_dir"])
    
    # [model]
    if config.has_section("model"):
        settings["model_name"] = config.get("model", "name", fallback=settings["model_name"])
        settings["device"] = config.get("model", "device", fallback=settings["device"])
    
    # [audio]
    if config.has_section("audio"):
        settings["overlay"] = config.getboolean("audio", "overlay", fallback=settings["overlay"])
        settings["audio_volume"] = config.getfloat("audio", "audio_volume", fallback=settings["audio_volume"])
        settings["original_volume"] = config.getfloat("audio", "original_volume", fallback=settings["original_volume"])
    
    # [processing]
    if config.has_section("processing"):
        settings["skip_existing"] = config.getboolean("processing", "skip_existing", fallback=settings["skip_existing"])
    
    return settings


def main():
    print("\n" + "=" * 60)
    print("🎬 Style-Bert-VITS2 吹き替えバッチ処理")
    print("=" * 60)
    
    # 利用可能なモデルを取得
    models = get_available_models()
    if not models:
        print("❌ model_assets/ にモデルが見つかりません。")
        return 1
    
    # 話者を選択
    model_name = select_model(models)
    
    # 設定を読み込む
    config = load_config()
    config["model_name"] = model_name  # 選択したモデルで上書き
    
    # 相対パスを絶対パスに変換
    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    
    if not input_dir.is_absolute():
        input_dir = PROJECT_ROOT / input_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    
    print("📋 設定:")
    print(f"   話者: {config['model_name']}")
    print(f"   入力: {input_dir}")
    print(f"   出力: {output_dir}")
    print(f"   デバイス: {config['device']}")
    print()
    
    # ファイルペアを検出
    from dubbing_tools.src.batch_processor import create_batch_from_directory
    
    print("📂 ファイルを検索中...")
    try:
        video_paths, srt_paths, output_paths = create_batch_from_directory(
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            recursive=True,
            preserve_structure=True,
            suffix="",
            skip_existing=config["skip_existing"],
        )
    except Exception as e:
        print(f"❌ エラー: {e}")
        return 1
    
    if not video_paths:
        print("❌ 処理対象のファイルがありません。")
        return 1
    
    print(f"   検出: {len(video_paths)}件\n")
    
    # 確認
    print("処理を開始しますか？ [Y/n] ", end="")
    try:
        answer = input().strip().lower()
        if answer and answer != 'y':
            print("キャンセルしました。")
            return 0
    except KeyboardInterrupt:
        print("\nキャンセルしました。")
        return 0
    
    # モデルを初期化
    from dubbing_tools.src.dubbing_automation import DubbingAutomation
    
    print("\n🤖 モデルを読み込み中...")
    try:
        automation = DubbingAutomation(
            model_name=config["model_name"],
            device=config["device"],
        )
    except Exception as e:
        print(f"❌ モデル読み込みエラー: {e}")
        return 1
    
    # 一括処理実行
    print("\n🎬 処理開始...\n")
    
    completed = 0
    failed = 0
    
    for i, (video_path, srt_path, output_path) in enumerate(
        zip(video_paths, srt_paths, output_paths), 1
    ):
        video_name = Path(video_path).name
        filename_without_ext = Path(video_path).stem
        print(f"[{i}/{len(video_paths)}] {video_name}")
        
        # ファイル名が続編（xx-2以上）かどうかを判定
        is_sequel = is_continuation(filename_without_ext)
        overlay = config["overlay"]
        intro_duration = 0.0
        include_intro = not is_sequel  # 続編でなければ冒頭音声を入れる
        
        # 続編でない場合、冒頭5秒のみ元音声を重ねる（標準動作）
        if include_intro:
            overlay = True
            intro_duration = 5.0
            print(f"  📝 冒頭5秒のみ元音声を重ねます")
        else:
            print(f"  📝 続編ファイル - 冒頭音声をスキップします")
        
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            automation.create_dubbed_video(
                video_path=video_path,
                srt_path=srt_path,
                output_path=output_path,
                overlay=overlay,
                audio_volume=config["audio_volume"],
                original_volume=config["original_volume"],
                intro_only=include_intro,
            )
            
            completed += 1
            print(f"  ✅ 完了\n")
            
        except Exception as e:
            failed += 1
            logger.error(f"処理エラー: {video_name}", exc_info=True)
            print(f"  ❌ エラー: {e}\n")
            continue
    
    # 結果表示
    print("=" * 60)
    print(f"📊 結果: 成功 {completed} / 失敗 {failed} / 合計 {len(video_paths)}")
    print("=" * 60)
    
    if completed > 0:
        print(f"\n✅ 出力先: {output_dir}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
