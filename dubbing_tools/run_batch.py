"""
バッチ吹き替え処理 - メインエントリーポイント

使用方法:
    python dubbing_tools/run_batch.py
    
話者を選択式で選んで一括処理を開始します。
中断しても .dubbing_progress.json を使って続きから再開できます。
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
        "enable_async_io": True,
        "download_pool_size": 3,
        "max_upload_threads": 2,
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
    
    # [async_io] - 新規追加
    if config.has_section("async_io"):
        settings["enable_async_io"] = config.getboolean("async_io", "enable", fallback=settings["enable_async_io"])
        settings["download_pool_size"] = config.getint("async_io", "download_pool_size", fallback=settings["download_pool_size"])
        settings["max_upload_threads"] = config.getint("async_io", "max_upload_threads", fallback=settings["max_upload_threads"])
    
    return settings


def ask_resume_or_new(progress_manager: ProgressManager) -> str:
    """
    既存の進捗がある場合、再開するか新規開始するか確認
    
    Returns:
        "resume": 再開
        "new": 新規開始
        "cancel": キャンセル
    """
    info = progress_manager.get_resumable_info()
    
    print("\n" + "=" * 60)
    print("📂 前回の処理が中断されています")
    print("=" * 60)
    print(f"   セッションID: {info['session_id']}")
    print(f"   モデル: {info['model_name']}")
    print(f"   開始日時: {info['created_at']}")
    print(f"   合計: {info['total']}件")
    print(f"   完了: {info['completed']}件")
    print(f"   失敗: {info['failed']}件")
    print(f"   残り: {info['pending']}件")
    print()
    
    while True:
        print("どうしますか？")
        print("  [1] 続きから再開する")
        print("  [2] 最初からやり直す（進捗をクリア）")
        print("  [3] キャンセル")
        print()
        
        try:
            choice = input("番号を入力 > ").strip()
            if choice == "1":
                return "resume"
            elif choice == "2":
                confirm = input("本当に進捗をクリアしますか？ [y/N] > ").strip().lower()
                if confirm == 'y':
                    progress_manager.clear_progress()
                    return "new"
                else:
                    continue
            elif choice == "3":
                return "cancel"
            else:
                print("❌ 1, 2, 3 のいずれかを入力してください。")
        except KeyboardInterrupt:
            print("\n\nキャンセルしました。")
            return "cancel"


def main():
    print("\n" + "=" * 60)
    print("🎬 Style-Bert-VITS2 吹き替えバッチ処理")
    print("   (中断しても続きから再開できます)")
    print("=" * 60)
    
    # 設定を読み込む
    config = load_config()
    
    # 相対パスを絶対パスに変換
    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    
    if not input_dir.is_absolute():
        input_dir = PROJECT_ROOT / input_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    
    # 進捗管理の初期化
    progress_manager = ProgressManager(str(output_dir))
    
    # 既存の進捗があるか確認
    resume_mode = False
    if progress_manager.has_existing_progress():
        progress_manager.load_progress()
        pending = progress_manager.get_pending_files()
        
        if pending:
            choice = ask_resume_or_new(progress_manager)
            if choice == "cancel":
                return 0
            elif choice == "resume":
                resume_mode = True
                # 前回のモデル名を使用
                config["model_name"] = progress_manager.progress.model_name
                print(f"\n✅ 前回のセッションから再開します（モデル: {config['model_name']}）\n")
        else:
            # 全て完了済み、進捗をクリア
            print("前回の処理は全て完了しています。新規処理を開始します。")
            progress_manager.clear_progress()
    
    # 再開モードでなければモデルを選択
    if not resume_mode:
        # 利用可能なモデルを取得
        models = get_available_models()
        if not models:
            print("❌ model_assets/ にモデルが見つかりません。")
            return 1
        
        # 話者を選択
        model_name = select_model(models)
        config["model_name"] = model_name
    
    print("📋 設定:")
    print(f"   話者: {config['model_name']}")
    print(f"   入力: {input_dir}")
    print(f"   出力: {output_dir}")
    print(f"   デバイス: {config['device']}")
    print()
    
    # ファイルペアを検出（再開モードでない場合のみ）
    from dubbing_tools.src.batch_processor import create_batch_from_directory
    
    if resume_mode:
        # 再開モード: 進捗ファイルから未処理のファイルを取得
        pending_files = progress_manager.get_pending_files()
        video_paths = [f.video_path for f in pending_files]
        srt_paths = [f.srt_path for f in pending_files]
        output_paths = [f.output_path for f in pending_files]
        
        print(f"📂 残り {len(video_paths)}件 を処理します\n")
    else:
        # 新規モード: ファイルを検索
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
        
        # 新しいセッションを作成
        progress_manager.create_new_session(
            model_name=config["model_name"],
            input_dir=str(input_dir),
            video_paths=video_paths,
            srt_paths=srt_paths,
            output_paths=output_paths,
        )
    
    # 確認
    print("処理を開始しますか？ [Y/n] ", end="")
    try:
        answer = input().strip().lower()
        if answer and answer != 'y':
            print("キャンセルしました。")
            print("💡 進捗は保存されています。次回起動時に再開できます。")
            return 0
    except KeyboardInterrupt:
        print("\nキャンセルしました。")
        print("💡 進捗は保存されています。次回起動時に再開できます。")
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
    print("💡 Ctrl+C で中断しても、次回続きから再開できます\n")
    
    # 非同期IOマネージャーの初期化
    from dubbing_tools.src.async_io_manager import AsyncIOManager
    
    async_io = None
    use_async_io = config.get("enable_async_io", True)
    
    if use_async_io:
        temp_dir = output_dir / ".temp_processing"
        async_io = AsyncIOManager(
            temp_dir=str(temp_dir),
            download_pool_size=config.get("download_pool_size", 3),
            max_upload_threads=config.get("max_upload_threads", 2),
            enable_async=True,
        )
        async_io.start()
        
        # ダウンロードタスクをキューに追加
        async_io.enqueue_downloads(video_paths, srt_paths)
        print(f"📥 非同期IO有効: ダウンロードプールサイズ={config.get('download_pool_size', 3)}, "
              f"アップロードスレッド数={config.get('max_upload_threads', 2)}\n")
    
    completed = 0
    failed = 0
    total = len(video_paths)
    
    try:
        for i, (video_path_orig, srt_path_orig, output_path) in enumerate(
            zip(video_paths, srt_paths, output_paths), 1
        ):
            video_name = Path(video_path_orig).name
            filename_without_ext = Path(video_path_orig).stem
            print(f"[{i}/{total}] {video_name}")
            
            # 処理中としてマーク
            progress_manager.mark_in_progress(output_path)
            
            # ファイル名が続編（xx-2以上）かどうかを判定
            is_sequel = is_continuation(filename_without_ext)
            overlay = config["overlay"]
            intro_duration = 0.0
            
            # 続編でない場合、冒頭5秒のみ元音声を重ねる（標準動作）
            if not is_sequel:
                overlay = True
                intro_duration = 5.0
                print(f"  📝 冒頭5秒のみ元音声を重ねます")
            else:
                print(f"  📝 続編ファイル - 冒頭音声をスキップします")
            
            try:
                # 非同期IOを使用する場合はダウンロード完了を待つ
                if use_async_io:
                    video_path, srt_path = async_io.get_downloaded_files(i - 1)
                    print(f"  📥 ダウンロード完了")
                else:
                    video_path = video_path_orig
                    srt_path = srt_path_orig
                
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                
                # 一時出力パスを使用（非同期アップロード用）
                if use_async_io:
                    temp_output = str(Path(output_path).parent / f".temp_{Path(output_path).name}")
                else:
                    temp_output = output_path
                
                automation.create_dubbed_video(
                    video_path=video_path,
                    srt_path=srt_path,
                    output_path=temp_output,
                    overlay=overlay,
                    audio_volume=config["audio_volume"],
                    original_volume=config["original_volume"],
                    intro_duration=intro_duration,
                )
                
                # 非同期アップロード
                if use_async_io:
                    # アップロードタスクをキューに追加し、処理を続行
                    cleanup_paths = [video_path, srt_path, temp_output]
                    async_io.enqueue_upload(temp_output, output_path, cleanup_paths)
                    print(f"  📤 アップロード中（バックグラウンド）")
                
                # 完了としてマーク
                progress_manager.mark_completed(output_path)
                completed += 1
                print(f"  ✅ 完了\n")
                
            except Exception as e:
                # 失敗としてマーク
                progress_manager.mark_failed(output_path, str(e))
                failed += 1
                logger.error(f"処理エラー: {video_name}", exc_info=True)
                print(f"  ❌ エラー: {e}\n")
                continue
                
    except KeyboardInterrupt:
        print("\n\n⚠️ 処理が中断されました")
        print("💡 進捗は保存されています。次回起動時に続きから再開できます。")
        if async_io:
            print("📤 アップロード完了を待機中...")
            async_io.stop(wait_uploads=True)
            async_io.cleanup_temp_dir()
        progress_manager.print_summary()
        return 1
    finally:
        # 非同期IOを停止
        if async_io:
            print("\n📤 残りのアップロードを完了中...")
            async_io.stop(wait_uploads=True)
            async_io.cleanup_temp_dir()
    
    # 結果表示
    print("=" * 60)
    print(f"📊 結果: 成功 {completed} / 失敗 {failed} / 合計 {total}")
    print("=" * 60)
    
    if completed > 0:
        print(f"\n✅ 出力先: {output_dir}")
    
    # 全て完了したら進捗ファイルを削除
    if failed == 0 and completed == total:
        progress_manager.clear_progress()
        print("✅ 全ての処理が完了しました！")
    else:
        progress_manager.print_summary()
        if failed > 0:
            print("\n💡 失敗したファイルは次回起動時にスキップされます。")
            print("   再処理するには進捗をクリアしてください。")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
