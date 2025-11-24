"""
動画結合モジュール

ffmpegを使用して動画と音声を結合します。
エンコードなしにストリームをコピーするため高速です。
"""

import subprocess
import os
from pathlib import Path
from typing import Optional


class VideoCombiner:
    """
    動画と音声を結合するクラス
    
    ffmpegを使用して、元の動画に生成した音声を重ねます。
    """
    
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        """
        Args:
            ffmpeg_path: ffmpegの実行ファイルパス(デフォルトはPATH上のffmpeg)
        """
        self.ffmpeg_path = ffmpeg_path
    
    def combine_audio(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        overlay: bool = True,
        audio_volume: float = 1.0,
        original_volume: float = 0.3,
        intro_duration: float = 0.0,
    ) -> bool:
        """
        動画と音声を結合
        
        元のコードのcombine_audio()を参考に実装。
        ffmpegでエンコードなしに動画ストリームをコピーし、音声のみ結合します。
        
        イントロ部分のみ元の音声を重ね、それ以降は生成音声のみにします。
        
        Args:
            video_path: 元の動画ファイルパス
            audio_path: 生成した音声ファイルパス(WAV)
            output_path: 出力動画ファイルパス
            overlay: Trueなら元の音声に重ねる、Falseなら置き換える
            audio_volume: 生成音声の音量(0.0~1.0以上)
            original_volume: 元の音声の音量(0.0~1.0以上、overlayがTrueの場合のみ)
            intro_duration: イントロの長さ(秒)。この時間までは元の音声を重ね、以降は生成音声のみ
            
        Returns:
            成功したらTrue
            
        Raises:
            FileNotFoundError: 入力ファイルが見つからない場合
            subprocess.CalledProcessError: ffmpegの実行に失敗した場合
        """
        # 入力ファイル存在チェック
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_path}")
        
        # 出力ディレクトリ作成
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # ffmpegコマンド構築
        if overlay and intro_duration > 0:
            # イントロ部分のみ元の音声を重ね、それ以降は生成音声のみ
            # シンプルな方法: イントロ部分で元の音声をフェードアウト
            filter_complex = (
                f"[0:a]volume={original_volume},"
                f"afade=t=out:st={intro_duration}:d=0.5[orig];"
                f"[1:a]volume={audio_volume}[gen];"
                f"[orig][gen]amix=inputs=2:duration=longest[aout]"
            )
            
            cmd = (
                f'"{self.ffmpeg_path}" -i "{video_path}" -i "{audio_path}" '
                f'-filter_complex "{filter_complex}" '
                f'-map 0:v:0 -map "[aout]" '
                f'-c:v copy -c:a aac '
                f'-y "{output_path}"'
            )
        elif overlay:
            # 全体で元の音声に重ねる（従来の動作）
            filter_complex = (
                f"[0:a]volume={original_volume}[a1];"
                f"[1:a]volume={audio_volume}[a2];"
                f"[a1][a2]amix=inputs=2:duration=longest[aout]"
            )
            
            cmd = (
                f'"{self.ffmpeg_path}" -i "{video_path}" -i "{audio_path}" '
                f'-filter_complex "{filter_complex}" '
                f'-map 0:v:0 -map "[aout]" '
                f'-c:v copy -c:a aac '
                f'-y "{output_path}"'
            )
        else:
            # 音声を置き換え（元のコードと同じロジック）
            cmd = (
                f'"{self.ffmpeg_path}" -i "{video_path}" -i "{audio_path}" '
                f'-c:v copy -c:a aac '
                f'-map 0:v:0 -map 1:a:0 '
                f'-y "{output_path}"'
            )
        
        # ffmpeg実行
        try:
            print(f"動画結合中: {video_path} + {audio_path} -> {output_path}")
            result = subprocess.run(
                cmd,
                check=True,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            print(f"動画結合完了: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"ffmpegエラー: {e}")
            print(f"stdout: {e.stdout}")
            print(f"stderr: {e.stderr}")
            raise
    
    def get_video_duration(self, video_path: str) -> float:
        """
        動画の長さを取得
        
        Args:
            video_path: 動画ファイルパス
            
        Returns:
            動画の長さ(秒)
            
        Raises:
            FileNotFoundError: ファイルが見つからない場合
            ValueError: 長さを取得できない場合
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")
        
        # ffprobeで長さを取得
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            duration = float(result.stdout.strip())
            return duration
        except (subprocess.CalledProcessError, ValueError) as e:
            raise ValueError(f"動画の長さを取得できません: {e}")
