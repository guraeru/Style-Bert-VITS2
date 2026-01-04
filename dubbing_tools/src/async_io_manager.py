"""
非同期IOマネージャー

共有ストレージを使用する場合のIOボトルネックを解消するため、
ダウンロードプール（事前ダウンロード）とアップロードの非同期化を実装します。

主な機能:
- ダウンロードプール: 処理の先読みで複数ファイルを事前ダウンロード
- 非同期アップロード: アップロード完了を待たずに次の処理へ
- 自動クリーンアップ: 処理完了後の一時ファイル削除
"""

import os
import shutil
import threading
import queue
from pathlib import Path
from typing import Optional, Tuple, Callable
from dataclasses import dataclass
from loguru import logger


@dataclass
class DownloadTask:
    """ダウンロードタスク"""
    video_src: str
    video_dst: str
    srt_src: str
    srt_dst: str
    index: int  # 処理順序


@dataclass
class UploadTask:
    """アップロードタスク"""
    src_path: str
    dst_path: str
    cleanup_paths: list  # アップロード後に削除するファイルパス


class AsyncIOManager:
    """
    非同期IOマネージャー
    
    ダウンロードプールと非同期アップロードでIOボトルネックを軽減します。
    
    Args:
        temp_dir: 一時ファイル保存ディレクトリ
        download_pool_size: ダウンロードプールサイズ（何件先までダウンロードするか）
        max_upload_threads: 最大アップロードスレッド数
        enable_async: 非同期処理を有効にするか（デバッグ用にFalseも可能）
    """
    
    def __init__(
        self,
        temp_dir: str,
        download_pool_size: int = 3,
        max_upload_threads: int = 2,
        enable_async: bool = True,
    ):
        self.temp_dir = Path(temp_dir)
        self.download_pool_size = download_pool_size
        self.max_upload_threads = max_upload_threads
        self.enable_async = enable_async
        
        # 一時ディレクトリ作成
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # ダウンロードキューとスレッド
        self.download_queue = queue.Queue()
        self.download_results = {}  # {index: (video_path, srt_path, error)}
        self.download_threads = []
        self.download_lock = threading.Lock()
        self.download_active = False
        
        # アップロードキューとスレッド
        self.upload_queue = queue.Queue()
        self.upload_threads = []
        self.upload_lock = threading.Lock()
        self.upload_active = False
        self.upload_errors = []
        
        logger.info(f"AsyncIOManager initialized: pool_size={download_pool_size}, "
                   f"upload_threads={max_upload_threads}, async={enable_async}")
    
    def start(self):
        """非同期処理を開始"""
        if not self.enable_async:
            logger.info("Async mode disabled, using synchronous IO")
            return
        
        # ダウンロードスレッド起動
        self.download_active = True
        download_thread = threading.Thread(target=self._download_worker, daemon=True)
        download_thread.start()
        self.download_threads.append(download_thread)
        
        # アップロードスレッド起動
        self.upload_active = True
        for i in range(self.max_upload_threads):
            upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
            upload_thread.start()
            self.upload_threads.append(upload_thread)
        
        logger.info(f"Started {len(self.download_threads)} download threads and "
                   f"{len(self.upload_threads)} upload threads")
    
    def stop(self, wait_uploads: bool = True, timeout: float = 30.0):
        """
        非同期処理を停止
        
        Args:
            wait_uploads: アップロード完了を待つか
            timeout: アップロード待機のタイムアウト（秒）
        """
        if not self.enable_async:
            return
        
        # ダウンロード停止
        self.download_active = False
        self.download_queue.put(None)  # 終了シグナル
        
        # アップロード停止（シグナル送信前にフラグをクリア）
        self.upload_active = False
        
        if wait_uploads:
            # 全アップロードが完了するまで待つ（タイムアウト付きqueue.join使用）
            import time
            from threading import Thread
            
            def join_with_timeout():
                self.upload_queue.join()
            
            join_thread = Thread(target=join_with_timeout, daemon=True)
            join_thread.start()
            join_thread.join(timeout=timeout)
            
            if join_thread.is_alive():
                logger.warning(f"Upload queue join timed out after {timeout}s")
        
        # 終了シグナルを全アップロードスレッドに送信
        for _ in range(len(self.upload_threads)):
            self.upload_queue.put(None)
        
        # スレッド終了待機（タイムアウト付き）
        join_timeout = 5.0
        for thread in self.download_threads:
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning(f"Download thread did not terminate within {join_timeout}s")
        
        for thread in self.upload_threads:
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning(f"Upload thread did not terminate within {join_timeout}s")
        
        logger.info("AsyncIOManager stopped")
        
        # アップロードエラーがあれば報告
        if self.upload_errors:
            logger.warning(f"{len(self.upload_errors)} upload errors occurred")
            for error in self.upload_errors[:5]:  # 最初の5件のみ表示
                logger.warning(f"  - {error}")
    
    def enqueue_downloads(
        self,
        video_paths: list,
        srt_paths: list,
    ):
        """
        ダウンロードタスクをキューに追加
        
        Args:
            video_paths: 元の動画ファイルパスリスト
            srt_paths: 元のSRTファイルパスリスト
        """
        if not self.enable_async:
            return
        
        for i, (video_src, srt_src) in enumerate(zip(video_paths, srt_paths)):
            # 一時ファイルパスを生成
            video_dst = self.temp_dir / f"video_{i}_{Path(video_src).name}"
            srt_dst = self.temp_dir / f"srt_{i}_{Path(srt_src).name}"
            
            task = DownloadTask(
                video_src=video_src,
                video_dst=str(video_dst),
                srt_src=srt_src,
                srt_dst=str(srt_dst),
                index=i,
            )
            self.download_queue.put(task)
        
        logger.info(f"Enqueued {len(video_paths)} download tasks")
    
    def get_downloaded_files(self, index: int, timeout: float = 300.0) -> Tuple[str, str]:
        """
        ダウンロード完了したファイルを取得
        
        Args:
            index: ファイルのインデックス
            timeout: タイムアウト時間（秒）
            
        Returns:
            (video_path, srt_path) のタプル
            
        Raises:
            TimeoutError: タイムアウトした場合
            RuntimeError: ダウンロードエラーが発生した場合
        """
        if not self.enable_async:
            # 同期モードでは何もしない（元のパスをそのまま使用）
            raise RuntimeError("Async mode is disabled")
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.download_lock:
                if index in self.download_results:
                    video_path, srt_path, error = self.download_results[index]
                    
                    if error:
                        raise RuntimeError(f"Download failed: {error}")
                    
                    # 結果を削除（メモリ節約）
                    del self.download_results[index]
                    return video_path, srt_path
            
            time.sleep(0.1)
        
        raise TimeoutError(f"Download timeout for index {index}")
    
    def enqueue_upload(
        self,
        src_path: str,
        dst_path: str,
        cleanup_paths: Optional[list] = None,
    ):
        """
        アップロードタスクをキューに追加
        
        Args:
            src_path: アップロード元ファイルパス
            dst_path: アップロード先ファイルパス
            cleanup_paths: アップロード後に削除するファイルパスリスト
        """
        if not self.enable_async:
            # 同期モードでは即座に実行
            self._upload_file(src_path, dst_path, cleanup_paths or [])
            return
        
        task = UploadTask(
            src_path=src_path,
            dst_path=dst_path,
            cleanup_paths=cleanup_paths or [],
        )
        self.upload_queue.put(task)
    
    def _download_worker(self):
        """ダウンロードワーカースレッド"""
        while self.download_active:
            task = None
            try:
                task = self.download_queue.get(timeout=1.0)
                if task is None:  # 終了シグナル
                    self.download_queue.task_done()
                    break
                
                # ダウンロード実行
                try:
                    self._download_files(task)
                    
                    with self.download_lock:
                        self.download_results[task.index] = (
                            task.video_dst,
                            task.srt_dst,
                            None,
                        )
                    
                except Exception as e:
                    logger.error(f"Download failed for index {task.index}: {e}")
                    with self.download_lock:
                        self.download_results[task.index] = (None, None, str(e))
                
                self.download_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Download worker error: {e}")
                if task is not None:
                    self.download_queue.task_done()
    
    def _upload_worker(self):
        """アップロードワーカースレッド"""
        while self.upload_active:
            task = None
            try:
                task = self.upload_queue.get(timeout=1.0)
                if task is None:  # 終了シグナル
                    self.upload_queue.task_done()
                    break
                
                # アップロード実行
                try:
                    self._upload_file(task.src_path, task.dst_path, task.cleanup_paths)
                except Exception as e:
                    error_msg = f"Upload failed: {task.src_path} -> {task.dst_path}: {e}"
                    logger.error(error_msg)
                    with self.upload_lock:
                        self.upload_errors.append(error_msg)
                
                self.upload_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Upload worker error: {e}")
                if task is not None:
                    self.upload_queue.task_done()
    
    def _download_files(self, task: DownloadTask):
        """
        ファイルをダウンロード（コピー）
        
        Args:
            task: ダウンロードタスク
        """
        logger.debug(f"Downloading files for index {task.index}")
        
        # 動画ファイルコピー
        if not os.path.exists(task.video_src):
            raise FileNotFoundError(f"Video file not found: {task.video_src}")
        shutil.copy2(task.video_src, task.video_dst)
        
        # SRTファイルコピー
        if not os.path.exists(task.srt_src):
            raise FileNotFoundError(f"SRT file not found: {task.srt_src}")
        shutil.copy2(task.srt_src, task.srt_dst)
        
        logger.debug(f"Downloaded files for index {task.index}")
    
    def _upload_file(self, src_path: str, dst_path: str, cleanup_paths: list):
        """
        ファイルをアップロード（コピー）し、クリーンアップ
        
        Args:
            src_path: アップロード元ファイルパス
            dst_path: アップロード先ファイルパス
            cleanup_paths: 削除するファイルパスリスト
        """
        logger.debug(f"Uploading: {src_path} -> {dst_path}")
        
        # 出力ディレクトリ作成
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        
        # ファイルコピー
        shutil.copy2(src_path, dst_path)
        
        # クリーンアップ
        for path in cleanup_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.debug(f"Cleaned up: {path}")
                except Exception as e:
                    logger.warning(f"Cleanup failed: {path}: {e}")
        
        logger.debug(f"Upload completed: {dst_path}")
    
    def cleanup_temp_dir(self):
        """一時ディレクトリをクリーンアップ"""
        if self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")
