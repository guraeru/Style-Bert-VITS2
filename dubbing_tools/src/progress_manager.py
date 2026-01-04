"""
進捗管理モジュール

バッチ処理の進捗状態を保存・復元し、中断からの再開をサポートします。
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class ProcessingStatus(str, Enum):
    """処理ステータス"""
    PENDING = "pending"      # 未処理
    IN_PROGRESS = "in_progress"  # 処理中
    COMPLETED = "completed"  # 完了
    FAILED = "failed"        # 失敗
    SKIPPED = "skipped"      # スキップ


@dataclass
class FileProgress:
    """ファイルの処理進捗"""
    video_path: str
    srt_path: str
    output_path: str
    status: str
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileProgress":
        return cls(**data)


@dataclass
class BatchProgress:
    """バッチ処理の進捗情報"""
    session_id: str
    model_name: str
    input_dir: str
    output_dir: str
    created_at: str
    updated_at: str
    total_files: int
    completed_count: int
    failed_count: int
    files: List[FileProgress]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "model_name": self.model_name,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_files": self.total_files,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "files": [f.to_dict() for f in self.files],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchProgress":
        files = [FileProgress.from_dict(f) for f in data.get("files", [])]
        return cls(
            session_id=data["session_id"],
            model_name=data["model_name"],
            input_dir=data["input_dir"],
            output_dir=data["output_dir"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            total_files=data["total_files"],
            completed_count=data["completed_count"],
            failed_count=data["failed_count"],
            files=files,
        )


class ProgressManager:
    """
    進捗管理クラス
    
    バッチ処理の進捗を.progress.jsonファイルに保存し、
    中断しても続きから再開できるようにします。
    """
    
    PROGRESS_FILENAME = ".dubbing_progress.json"
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: 出力ディレクトリ（進捗ファイルの保存先）
        """
        self.output_dir = Path(output_dir)
        self.progress_file = self.output_dir / self.PROGRESS_FILENAME
        self.progress: Optional[BatchProgress] = None
    
    def has_existing_progress(self) -> bool:
        """既存の進捗ファイルがあるか確認"""
        return self.progress_file.exists()
    
    def load_progress(self) -> Optional[BatchProgress]:
        """進捗ファイルを読み込む"""
        if not self.progress_file.exists():
            return None
        
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.progress = BatchProgress.from_dict(data)
            return self.progress
        except Exception as e:
            print(f"⚠️ 進捗ファイルの読み込みに失敗: {e}")
            return None
    
    def save_progress(self) -> bool:
        """進捗をファイルに保存"""
        if self.progress is None:
            return False
        
        try:
            # 出力ディレクトリがなければ作成
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # 更新日時を更新
            self.progress.updated_at = datetime.now().isoformat()
            
            # 一時ファイルに書き込んでからリネーム（原子的操作）
            temp_file = self.progress_file.with_suffix('.json.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress.to_dict(), f, ensure_ascii=False, indent=2)
            
            # リネーム（Windows対応）
            if self.progress_file.exists():
                os.remove(self.progress_file)
            os.rename(temp_file, self.progress_file)
            
            return True
        except Exception as e:
            print(f"⚠️ 進捗ファイルの保存に失敗: {e}")
            return False
    
    def create_new_session(
        self,
        model_name: str,
        input_dir: str,
        video_paths: List[str],
        srt_paths: List[str],
        output_paths: List[str],
    ) -> BatchProgress:
        """
        新しいバッチ処理セッションを作成
        
        Args:
            model_name: モデル名
            input_dir: 入力ディレクトリ
            video_paths: 動画ファイルパスのリスト
            srt_paths: SRTファイルパスのリスト
            output_paths: 出力ファイルパスのリスト
        """
        now = datetime.now().isoformat()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        files = []
        for video, srt, output in zip(video_paths, srt_paths, output_paths):
            files.append(FileProgress(
                video_path=video,
                srt_path=srt,
                output_path=output,
                status=ProcessingStatus.PENDING.value,
            ))
        
        self.progress = BatchProgress(
            session_id=session_id,
            model_name=model_name,
            input_dir=input_dir,
            output_dir=str(self.output_dir),
            created_at=now,
            updated_at=now,
            total_files=len(files),
            completed_count=0,
            failed_count=0,
            files=files,
        )
        
        self.save_progress()
        return self.progress
    
    def get_pending_files(self) -> List[FileProgress]:
        """未処理・処理中のファイルを取得（再開用）"""
        if self.progress is None:
            return []
        
        pending = []
        for f in self.progress.files:
            # 未処理、処理中、失敗のファイルを返す（完了とスキップ以外）
            if f.status in [ProcessingStatus.PENDING.value, ProcessingStatus.IN_PROGRESS.value]:
                pending.append(f)
        
        return pending
    
    def get_resumable_info(self) -> Dict[str, Any]:
        """再開可能な情報を取得"""
        if self.progress is None:
            return {}
        
        pending = self.get_pending_files()
        completed = sum(1 for f in self.progress.files if f.status == ProcessingStatus.COMPLETED.value)
        failed = sum(1 for f in self.progress.files if f.status == ProcessingStatus.FAILED.value)
        
        return {
            "session_id": self.progress.session_id,
            "model_name": self.progress.model_name,
            "total": self.progress.total_files,
            "completed": completed,
            "failed": failed,
            "pending": len(pending),
            "created_at": self.progress.created_at,
        }
    
    def mark_in_progress(self, output_path: str) -> None:
        """ファイルを処理中としてマーク"""
        if self.progress is None:
            return
        
        for f in self.progress.files:
            if f.output_path == output_path:
                f.status = ProcessingStatus.IN_PROGRESS.value
                f.started_at = datetime.now().isoformat()
                break
        
        self.save_progress()
    
    def mark_completed(self, output_path: str) -> None:
        """ファイルを完了としてマーク"""
        if self.progress is None:
            return
        
        for f in self.progress.files:
            if f.output_path == output_path:
                f.status = ProcessingStatus.COMPLETED.value
                f.completed_at = datetime.now().isoformat()
                self.progress.completed_count += 1
                break
        
        self.save_progress()
    
    def mark_failed(self, output_path: str, error_message: str) -> None:
        """ファイルを失敗としてマーク"""
        if self.progress is None:
            return
        
        for f in self.progress.files:
            if f.output_path == output_path:
                f.status = ProcessingStatus.FAILED.value
                f.error_message = error_message
                f.completed_at = datetime.now().isoformat()
                self.progress.failed_count += 1
                break
        
        self.save_progress()
    
    def mark_skipped(self, output_path: str) -> None:
        """ファイルをスキップとしてマーク"""
        if self.progress is None:
            return
        
        for f in self.progress.files:
            if f.output_path == output_path:
                f.status = ProcessingStatus.SKIPPED.value
                break
        
        self.save_progress()
    
    def clear_progress(self) -> None:
        """進捗ファイルを削除"""
        if self.progress_file.exists():
            try:
                os.remove(self.progress_file)
                print(f"進捗ファイルを削除しました: {self.progress_file}")
            except Exception as e:
                print(f"⚠️ 進捗ファイルの削除に失敗: {e}")
        
        self.progress = None
    
    def print_summary(self) -> None:
        """進捗サマリーを表示"""
        if self.progress is None:
            print("進捗情報がありません。")
            return
        
        completed = sum(1 for f in self.progress.files if f.status == ProcessingStatus.COMPLETED.value)
        failed = sum(1 for f in self.progress.files if f.status == ProcessingStatus.FAILED.value)
        pending = sum(1 for f in self.progress.files if f.status in [ProcessingStatus.PENDING.value, ProcessingStatus.IN_PROGRESS.value])
        skipped = sum(1 for f in self.progress.files if f.status == ProcessingStatus.SKIPPED.value)
        
        print(f"\n📊 進捗状況:")
        print(f"   合計: {self.progress.total_files}件")
        print(f"   完了: {completed}件")
        print(f"   失敗: {failed}件")
        print(f"   未処理: {pending}件")
        if skipped > 0:
            print(f"   スキップ: {skipped}件")
