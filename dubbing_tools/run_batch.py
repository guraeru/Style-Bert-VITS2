"""
吹き替え処理 - メインエントリーポイント

使用方法:
    python dubbing_tools/run_batch.py                    # 対話式で全/単一セクション選択
    python dubbing_tools/run_batch.py --path "C:\\path"  # 指定パスを直接処理
    
話者を選択式で選んで処理を開始します。
中断しても .dubbing_progress.json を使って続きから再開できます。
"""

import sys
import re
import shutil
import configparser
import argparse
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from loguru import logger

# プロジェクトルートを自動検出
PROJECT_ROOT = Path(__file__).parent.parent
DUBBING_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 進捗管理モジュール
from dubbing_tools.src.progress_manager import ProgressManager

# ===== ロギング設定 =====
logger.remove()
logger.add(
    sys.stderr,
    format="<level>{time:HH:mm:ss}</level> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)


STAGED_TEMP_PATTERN = re.compile(r".*_[0-9a-f]{32}(?:\.mp4|\.srt|\.temp\.wav)$")


@dataclass
class DeployTask:
    """I/O配置タスクの追跡情報。"""

    future: Future[None]
    output_path: str
    display_name: str
    staged_result: Optional[Any] = None


def copy_video_passthrough(video_path: str, output_path: str) -> None:
    """字幕なし動画を最終出力へコピーする（I/Oプール実行用）。"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, output_path)


def cleanup_stale_workfiles(work_dir: Path, older_than_hours: int) -> int:
    """前回中断などで残った一時成果物を掃除する。"""

    if older_than_hours < 0:
        older_than_hours = 0

    if not work_dir.exists():
        return 0

    cutoff = time.time() - (older_than_hours * 3600)
    removed = 0

    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue

        name = path.name
        is_temp_candidate = (
            name.endswith(".part")
            or name.endswith(".tmp")
            or STAGED_TEMP_PATTERN.fullmatch(name) is not None
        )
        if not is_temp_candidate:
            continue

        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                removed += 1
        except Exception:
            continue

    return removed


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


def get_available_models() -> list[str]:
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


def select_model(models: list[str]) -> str:
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


def select_section_or_all(input_dir: Path) -> tuple[Optional[Path], str]:
    """
    全セクション処理か単一セクション選択かを対話式で決定する。

    Returns:
        (選択されたinput_dir, mode)  mode = "all" | "section" | "cancel"
    """
    subdirs = sorted([d for d in input_dir.iterdir() if d.is_dir() and not d.name.startswith('.')])

    if not subdirs:
        # サブディレクトリがなければ全処理のみ
        return input_dir, "all"

    print("\n" + "=" * 60)
    print("📂 処理モードを選択してください")
    print("=" * 60)
    print("  [1] 全セクションを一括処理する")
    print("  [2] 特定のセクションを選んで処理する")
    print()

    while True:
        try:
            mode_choice = input("番号を入力 > ").strip()
            if mode_choice == "1":
                return input_dir, "all"
            elif mode_choice == "2":
                break
            else:
                print("❌ 1 か 2 を入力してください。")
        except KeyboardInterrupt:
            print("\n\nキャンセルしました。")
            return None, "cancel"

    # セクション一覧を表示
    print("\n" + "=" * 60)
    print("📂 処理するセクションを選んでください")
    print("=" * 60)
    print()

    for i, d in enumerate(subdirs, 1):
        mp4_count = len(list(d.rglob("*.mp4")))
        srt_count = len(list(d.rglob("*.srt")))
        print(f"  [{i}] {d.name}  ({mp4_count}個の動画, {srt_count}個の字幕)")

    print()

    while True:
        try:
            choice = input("番号を入力 > ").strip()
            if not choice:
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(subdirs):
                selected = subdirs[idx]
                print(f"\n✅ 選択: {selected.name}\n")
                return selected, "section"
            else:
                print("❌ 無効な番号です。もう一度入力してください。")
        except ValueError:
            print("❌ 数字を入力してください。")
        except KeyboardInterrupt:
            print("\n\nキャンセルしました。")
            return None, "cancel"


def load_config() -> dict[str, Any]:
    """config.ini から設定を読み込む"""
    config_path = DUBBING_TOOLS_DIR / "config.ini"
    
    # デフォルト設定
    settings = {
        "input_dir": "input_mp4",
        "output_dir": "output_mp4",
        "work_dir": "temp/dubbing_work",
        "model_name": "jvnv-F1-jp",
        "device": "cuda",
        "overlay": True,
        "audio_volume": 1.0,
        "original_volume": 0.3,
        "skip_existing": True,
        "io_pool_workers": 2,
        "io_queue_depth": 2,
        "work_cleanup_hours": 24,
    }
    
    if not config_path.exists():
        return settings
    
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    
    # [paths]
    if config.has_section("paths"):
        settings["input_dir"] = config.get("paths", "input_dir", fallback=settings["input_dir"])
        settings["output_dir"] = config.get("paths", "output_dir", fallback=settings["output_dir"])
        settings["work_dir"] = config.get("paths", "work_dir", fallback=settings["work_dir"])
    
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
        settings["io_pool_workers"] = config.getint("processing", "io_pool_workers", fallback=settings["io_pool_workers"])
        settings["io_queue_depth"] = config.getint("processing", "io_queue_depth", fallback=settings["io_queue_depth"])
        settings["work_cleanup_hours"] = config.getint("processing", "work_cleanup_hours", fallback=settings["work_cleanup_hours"])
    
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
    parser = argparse.ArgumentParser(
        description="吹き替え処理を実行します（全セクション一括 or 単一セクション選択）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python dubbing_tools/run_batch.py
  python dubbing_tools/run_batch.py --path "C:\\path\\to\\directory"
  python dubbing_tools/run_batch.py -p "C:\\input\\directory"
        """
    )
    parser.add_argument("--path", "-p", type=str, help="処理対象ディレクトリ（指定しない場合はデフォルト）")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("🎬 Style-Bert-VITS2 吹き替え処理")
    print("   (中断しても続きから再開できます)")
    print("=" * 60)
    
    # 設定を読み込む
    config = load_config()
    
    # 相対パスを絶対パスに変換
    if args.path:
        input_dir = Path(args.path)
    else:
        input_dir = Path(config["input_dir"])
    
    output_dir = Path(config["output_dir"])
    work_dir = Path(config["work_dir"])
    
    if not input_dir.is_absolute():
        input_dir = PROJECT_ROOT / input_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    if not work_dir.is_absolute():
        work_dir = PROJECT_ROOT / work_dir

    # --path 未指定時のみセクション選択UIを表示
    if not args.path:
        if not input_dir.exists():
            print(f"❌ 入力ディレクトリが見つかりません: {input_dir}")
            return 1
        selected, mode = select_section_or_all(input_dir)
        if mode == "cancel":
            return 0
        if mode == "section":
            # 選択セクションのみ処理。出力先にもセクション名を付加
            input_dir = selected
            output_dir = output_dir / selected.name

    # 作業領域は必ずローカルのプロジェクト配下を想定（NAS先で中間生成しない）
    work_dir.mkdir(parents=True, exist_ok=True)

    removed_count = cleanup_stale_workfiles(work_dir, int(config.get("work_cleanup_hours", 24)))
    if removed_count > 0:
        print(f"🧹 前回の一時ファイルをクリーンアップ: {removed_count}件")
    
    # 進捗管理の初期化（input_dir/output_dir確定後）
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
                if progress_manager.progress is None:
                    raise RuntimeError("進捗情報の読み込みに失敗しました")
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
    print(f"   作業: {work_dir}")
    print(f"   デバイス: {config['device']}")
    print(f"   I/Oプール: workers={config['io_pool_workers']} / queue_depth={config['io_queue_depth']}")
    print()
    
    # ファイルペアを検出（再開モードでない場合のみ）
    from dubbing_tools.src.batch_processor import create_batch_from_directory
    
    if resume_mode:
        # 再開モード: 進捗ファイルから未処理のファイルを取得
        pending_files = progress_manager.get_pending_files()
        video_paths = [f.video_path for f in pending_files]
        srt_paths = [f.srt_path for f in pending_files]
        output_paths = [f.output_path for f in pending_files]
        copy_only_flags = [f.copy_only for f in pending_files]
        
        print(f"📂 残り {len(video_paths)}件 を処理します\n")
    else:
        # 新規モード: ファイルを検索
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
            work_root_dir=str(work_dir),
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

    io_workers = max(1, int(config.get("io_pool_workers", 2)))
    io_queue_depth = max(1, int(config.get("io_queue_depth", 2)))
    deploy_futures: deque[DeployTask] = deque()

    def finalize_deploy_task(task: DeployTask) -> None:
        """I/Oタスク1件の結果を進捗へ反映する。"""

        nonlocal completed, failed

        try:
            task.future.result()
            progress_manager.mark_completed(task.output_path)
            completed += 1
            print(f"  ✅ 完了（I/O配置済み）: {task.display_name}\n")
        except Exception as e:
            progress_manager.mark_failed(task.output_path, str(e))
            failed += 1
            logger.error(f"I/O配置エラー: {task.display_name}", exc_info=True)
            print(f"  ❌ I/O配置エラー: {e}\n")

    def flush_completed_deployments() -> None:
        """完了済みのI/Oタスクだけを回収する。"""

        while deploy_futures and deploy_futures[0].future.done():
            task = deploy_futures.popleft()
            finalize_deploy_task(task)

    def wait_for_oldest_deployment() -> None:
        """キュー圧迫時に最古のI/Oタスク1件だけ待機してスロットを空ける。"""

        if not deploy_futures:
            return

        task = deploy_futures.popleft()
        finalize_deploy_task(task)

    def cancel_pending_deployments() -> int:
        """未開始のI/Oタスクをキャンセルし、対応する一時成果物を掃除する。"""

        canceled = 0
        kept: deque[DeployTask] = deque()

        while deploy_futures:
            task = deploy_futures.popleft()
            if task.future.cancel():
                canceled += 1
                if task.staged_result is not None:
                    automation.cleanup_staged_output(task.staged_result)
                continue
            kept.append(task)

        deploy_futures.extend(kept)
        return canceled
    
    io_pool = ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="dubbing-io")
    _interrupted = False
    try:
        try:
            for i, (video_path, srt_path, output_path, copy_only) in enumerate(
                zip(video_paths, srt_paths, output_paths, copy_only_flags), 1
            ):
                video_name = Path(video_path).name
                filename_without_ext = Path(video_path).stem
                print(f"[{i}/{total}] {video_name}")

                progress_manager.mark_in_progress(output_path)

                try:
                    if copy_only:
                        print("  📋 字幕なし→動画コピーをI/Oプールへ投入します")
                        future = io_pool.submit(copy_video_passthrough, video_path, output_path)
                        deploy_futures.append(DeployTask(future=future, output_path=output_path, display_name=video_name))
                    else:
                        is_sequel = is_continuation(filename_without_ext)
                        overlay = config["overlay"]
                        intro_duration = 0.0

                        if not is_sequel:
                            overlay = True
                            intro_duration = 5.0
                            print("  📝 冒頭5秒のみ元音声と吹き替え音声をミックスします")
                        else:
                            overlay = False
                            print("  📝 吹き替え音声のみを使用します（元音声なし）")

                        staged = automation.create_dubbed_video_to_staging(
                            video_path=video_path,
                            srt_path=srt_path,
                            output_path=output_path,
                            work_dir=str(work_dir),
                            overlay=overlay,
                            audio_volume=config["audio_volume"],
                            original_volume=config["original_volume"],
                            intro_duration=intro_duration,
                        )
                        future = io_pool.submit(automation.deploy_staged_output, staged)
                        deploy_futures.append(
                            DeployTask(
                                future=future,
                                output_path=output_path,
                                display_name=video_name,
                                staged_result=staged,
                            )
                        )
                        print("  📦 最終配置をI/Oプールへ投入しました（GPUは次の処理を継続）")

                    flush_completed_deployments()
                    while len(deploy_futures) > io_queue_depth:
                        wait_for_oldest_deployment()

                except Exception as e:
                    progress_manager.mark_failed(output_path, str(e))
                    failed += 1
                    logger.error(f"処理エラー: {video_name}", exc_info=True)
                    print(f"  ❌ エラー: {e}\n")
                    continue

            # 残タスクを回収
            while deploy_futures:
                wait_for_oldest_deployment()

        except KeyboardInterrupt:
            _interrupted = True
            print("\n\n⚠️ 処理が中断されました")
            print("⏳ 完了済みI/Oを反映し、未開始I/Oをキャンセルします...")
            flush_completed_deployments()
            canceled = cancel_pending_deployments()
            io_pool.shutdown(wait=False, cancel_futures=True)
            if canceled > 0:
                print(f"🧹 キャンセル済みI/Oタスクの一時ファイルを掃除: {canceled}件")
            # 中断されたアイテムをpendingに戻し、次回再試行できるようにする
            reset_count = progress_manager.reset_in_progress_to_pending()
            if reset_count > 0:
                print(f"🔄 処理中だったアイテムを未処理に戻しました: {reset_count}件")
            print("💡 進捗は保存されています。次回起動時に続きから再開できます。")
            progress_manager.print_summary()
            return 1
    finally:
        if not _interrupted:
            # 保険: 例外経路でも完了済みタスクを可能な限り反映
            flush_completed_deployments()
        if 'io_pool' in locals():
            io_pool.shutdown(wait=False, cancel_futures=False)
    
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
