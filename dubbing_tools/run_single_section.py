"""
単一セクション吹き替え処理 - カスタムディレクトリ対応版

使用方法:
    python dubbing_tools/run_single_section.py
    または
    python dubbing_tools/run_single_section.py --path "C:\\path\\to\\section"
    
セクションを選択式で選んで処理を実行します。
"""

import sys
import re
import shutil
import configparser
import argparse
from pathlib import Path
from loguru import logger

# プロジェクトルートを自動検出
PROJECT_ROOT = Path(__file__).parent.parent
DUBBING_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 進捗管理モジュール
from dubbing_tools.src.progress_manager import ProgressManager, ProcessingStatus

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
    """
    match = re.match(r'^(\d+)(?:-(\d+))?', filename)
    if not match:
        return False
    
    part_num = int(match.group(2)) if match.group(2) else None
    
    if part_num is None:
        return False
    
    if part_num == 1:
        return False
    
    return True


def get_available_models():
    """利用可能なモデル一覧を取得"""
    model_dir = PROJECT_ROOT / "model_assets"
    if not model_dir.exists():
        return []
    
    models = []
    for d in model_dir.iterdir():
        if d.is_dir() and not d.name.startswith('.'):
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
    
    if config.has_section("paths"):
        settings["input_dir"] = config.get("paths", "input_dir", fallback=settings["input_dir"])
        settings["output_dir"] = config.get("paths", "output_dir", fallback=settings["output_dir"])
    
    if config.has_section("model"):
        settings["model_name"] = config.get("model", "name", fallback=settings["model_name"])
        settings["device"] = config.get("model", "device", fallback=settings["device"])
    
    if config.has_section("audio"):
        settings["overlay"] = config.getboolean("audio", "overlay", fallback=settings["overlay"])
        settings["audio_volume"] = config.getfloat("audio", "audio_volume", fallback=settings["audio_volume"])
        settings["original_volume"] = config.getfloat("audio", "original_volume", fallback=settings["original_volume"])
    
    if config.has_section("processing"):
        settings["skip_existing"] = config.getboolean("processing", "skip_existing", fallback=settings["skip_existing"])
    
    return settings


def main():
    parser = argparse.ArgumentParser(
        description="単一セクションの吹き替え処理を実行します",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python dubbing_tools/run_single_section.py
  python dubbing_tools/run_single_section.py --path "C:\\path\\to\\section"
        """
    )
    parser.add_argument("--path", "-p", type=str, help="処理対象のセクションパス（指定しない場合は選択UI）")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("🎬 Style-Bert-VITS2 単一セクション吹き替え処理")
    print("=" * 60)
    
    config = load_config()
    
    # 処理対象ディレクトリを決定
    if args.path:
        input_dir = Path(args.path)
        if not input_dir.exists():
            print(f"❌ ディレクトリが見つかりません: {input_dir}")
            return 1
    else:
        # セクション選択UI
        print("\n" + "=" * 60)
        print("📂 処理対象セクションを選択してください")
        print("=" * 60)
        
        # デフォルトinput_dirを確認
        default_input = Path(config["input_dir"])
        if not default_input.is_absolute():
            default_input = PROJECT_ROOT / default_input
        
        if not default_input.exists():
            print(f"❌ デフォルト入力ディレクトリが見つかりません: {default_input}")
            custom_path = input("カスタムパスを入力してください > ").strip()
            if not custom_path:
                print("キャンセルしました。")
                return 0
            input_dir = Path(custom_path)
        else:
            input_dir = default_input
        
        # ディレクトリ一覧を表示
        subdirs = sorted([d for d in input_dir.iterdir() if d.is_dir()])
        
        if not subdirs:
            print(f"❌ セクションが見つかりません: {input_dir}")
            return 1
        
        print()
        for i, d in enumerate(subdirs, 1):
            # ファイル数を表示（サブディレクトリ内も再帰的にカウント）
            file_count = len(list(d.rglob("*.mp4")))
            srt_count = len(list(d.rglob("*.srt")))
            print(f"  [{i}] {d.name} ({file_count}個のビデオ, {srt_count}個の字幕)")
        
        print()
        
        while True:
            try:
                choice = input("番号を入力 > ").strip()
                if not choice:
                    continue
                
                idx = int(choice) - 1
                if 0 <= idx < len(subdirs):
                    input_dir = subdirs[idx]
                    print(f"\n✅ 選択: {input_dir.name}\n")
                    break
                else:
                    print("❌ 無効な番号です。もう一度入力してください。")
            except ValueError:
                print("❌ 数字を入力してください。")
            except KeyboardInterrupt:
                print("\n\nキャンセルしました。")
                return 0
    
    # 出力ディレクトリを設定
    output_dir = Path(config["output_dir"])
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    
    # セクション名から出力サブディレクトリを作成
    relative_name = input_dir.name
    output_dir = output_dir / relative_name
    
    # 進捗管理の初期化
    progress_manager = ProgressManager(str(output_dir.parent))
    
    # 既存の進捗を確認
    if progress_manager.has_existing_progress():
        progress_manager.load_progress()
        pending = progress_manager.get_pending_files()
        
        if pending:
            info = progress_manager.get_resumable_info()
            print("\n" + "=" * 60)
            print("📂 前回の処理が中断されています")
            print("=" * 60)
            print(f"   完了: {info['completed']}件 / 失敗: {info['failed']}件 / 残り: {info['pending']}件")
            print()
            
            try:
                choice = input("続きから再開しますか？ [Y/n] > ").strip().lower()
                if choice == 'n':
                    progress_manager.clear_progress()
                else:
                    config["model_name"] = progress_manager.progress.model_name
                    print(f"\n✅ 続きから再開します（モデル: {config['model_name']}）\n")
            except KeyboardInterrupt:
                print("\nキャンセルしました。")
                return 0
        else:
            progress_manager.clear_progress()
    
    # モデル選択（再開でない場合）
    if not progress_manager.has_existing_progress():
        models = get_available_models()
        if not models:
            print("❌ model_assets/ にモデルが見つかりません。")
            return 1
        
        model_name = select_model(models)
        config["model_name"] = model_name
    
    print("📋 設定:")
    print(f"   セクション: {input_dir.name}")
    print(f"   話者: {config['model_name']}")
    print(f"   入力: {input_dir}")
    print(f"   出力: {output_dir}")
    print(f"   デバイス: {config['device']}")
    print()
    
    # ファイル検出
    from dubbing_tools.src.batch_processor import create_batch_from_directory
    
    print("📂 ファイルを検索中...")
    try:
        video_paths, srt_paths, output_paths, copy_only_flags = create_batch_from_directory(
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
    
    dub_count = sum(1 for f in copy_only_flags if not f)
    copy_count = sum(1 for f in copy_only_flags if f)
    print(f"   検出: {len(video_paths)}件（吹き替え: {dub_count}件 / コピーのみ: {copy_count}件）\n")
    
    # 新しいセッションを作成
    progress_manager.create_new_session(
        model_name=config["model_name"],
        input_dir=str(input_dir),
        video_paths=video_paths,
        srt_paths=srt_paths,
        output_paths=output_paths,
        copy_only_flags=copy_only_flags,
    )
    
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
    
    # モデル初期化
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
    print("💡 Ctrl+C で中断しても、次回続きから再開できます\n")
    
    completed = 0
    failed = 0
    total = len(video_paths)
    
    try:
        for i, (video_path, srt_path, output_path, copy_only) in enumerate(
            zip(video_paths, srt_paths, output_paths, copy_only_flags), 1
        ):
            video_name = Path(video_path).name
            filename_without_ext = Path(video_path).stem
            print(f"[{i}/{total}] {video_name}")
            
            progress_manager.mark_in_progress(output_path)
            
            try:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                
                if copy_only:
                    print(f"  📋 字幕なし→動画をそのままコピーします")
                    shutil.copy2(video_path, output_path)
                else:
                    is_sequel = is_continuation(filename_without_ext)
                    overlay = config["overlay"]
                    intro_duration = 0.0
                    
                    if not is_sequel:
                        overlay = True
                        intro_duration = 5.0
                        print(f"  📝 冒頭5秒のみ元音声と吹き替え音声をミックスします")
                    else:
                        overlay = False
                        print(f"  📝 吹き替え音声のみを使用します（元音声なし）")
                    
                    automation.create_dubbed_video(
                        video_path=video_path,
                        srt_path=srt_path,
                        output_path=output_path,
                        overlay=overlay,
                        audio_volume=config["audio_volume"],
                        original_volume=config["original_volume"],
                        intro_duration=intro_duration,
                    )
                
                progress_manager.mark_completed(output_path)
                completed += 1
                print(f"  ✅ 完了\n")
                
            except Exception as e:
                progress_manager.mark_failed(output_path, str(e))
                failed += 1
                logger.error(f"処理エラー: {video_name}", exc_info=True)
                print(f"  ❌ エラー: {e}\n")
                continue
                
    except KeyboardInterrupt:
        print("\n\n⚠️ 処理が中断されました")
        print("💡 進捗は保存されています。次回起動時に続きから再開できます。")
        progress_manager.print_summary()
        return 1
    
    # 結果表示
    print("=" * 60)
    print(f"📊 結果: 成功 {completed} / 失敗 {failed} / 合計 {total}")
    print("=" * 60)
    
    if completed > 0:
        print(f"\n✅ 出力先: {output_dir}")
    
    if failed == 0 and completed == total:
        progress_manager.clear_progress()
        print("✅ 全ての処理が完了しました！")
    else:
        progress_manager.print_summary()
        if failed > 0:
            print("\n💡 失敗したファイルは次回起動時にスキップされます。")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
