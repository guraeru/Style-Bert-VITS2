"""
吹き替え自動化メインモジュール

SRT解析、音声生成、動画結合を統合したメインクラスです。
"""

import os
import shutil
import time
from uuid import uuid4
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from style_bert_vits2.tts_model import TTSModel
from .srt_parser import SRTParser
from .audio_generator import AudioGenerator
from .video_combiner import VideoCombiner


@dataclass
class StagedDubResult:
    """ローカル作業領域に生成済みの中間成果物を表す。"""

    final_output_path: Path
    staging_video_path: Path
    staging_srt_path: Path


class DubbingAutomation:
    """
    吹き替え自動化クラス
    
    SRTファイルから音声を生成し、元の動画と結合して吹き替え動画を作成します。
    
    重要なポリシー:
    - 音声カットは一切行いません
    - 音声が長すぎる場合は話速を調整して再生成します
    """
    
    def __init__(
        self,
        model_name: str,
        device: str = "cuda",
        ffmpeg_path: str = "ffmpeg",
        tolerance_seconds: float = 60.0,
        min_length_scale: float = 0.5,
        work_root_dir: Optional[str] = None,
    ):
        """
        Args:
            model_name: モデル名（model_assets内のフォルダ名）
            device: 使用デバイス("cuda" or "cpu")
            ffmpeg_path: ffmpegの実行ファイルパス
            tolerance_seconds: 許容超過時間(秒)、デフォルト60秒
            min_length_scale: 最小話速(0.5なら最速2倍速)
        """
        self.tolerance_seconds = tolerance_seconds
        self.min_length_scale = min_length_scale
        
        # モデルパスを自動構築
        # ファイル: dubbing_tools/src/dubbing_automation.py
        # → 親: dubbing_tools/src
        # → 親の親: dubbing_tools
        # → 親の親の親: プロジェクトルート
        project_root = Path(__file__).parent.parent.parent
        if work_root_dir is None:
            # デフォルトはプロジェクト相対temp配下を作業領域にする
            self.work_root_dir = project_root / "temp" / "dubbing_work"
        else:
            self.work_root_dir = Path(work_root_dir)

        self.work_root_dir.mkdir(parents=True, exist_ok=True)

        model_dir = project_root / "model_assets" / model_name
        model_path = None
        
        # .safetensorsファイルを検索
        if model_dir.exists():
            for file in model_dir.glob("*.safetensors"):
                model_path = file
                break
        
        if not model_path:
            raise FileNotFoundError(f"モデルファイルが見つかりません: {model_dir.absolute()}")
        
        config_path = model_dir / "config.json"
        style_vec_path = model_dir / "style_vectors.npy"
        
        if not config_path.exists():
            raise FileNotFoundError(f"config.jsonが見つかりません: {config_path}")
        if not style_vec_path.exists():
            raise FileNotFoundError(f"style_vectors.npyが見つかりません: {style_vec_path}")
        
        # TTSモデル初期化
        print(f"TTSモデルを読み込み中: {model_name}")
        print(f"  モデルファイル: {model_path}")
        self.tts_model = TTSModel(
            model_path=model_path,
            config_path=config_path,
            style_vec_path=style_vec_path,
            device=device,
        )
        print("TTSモデル読み込み完了")
        
        # 各モジュール初期化
        self.audio_generator = AudioGenerator(
            tts_model=self.tts_model,
            min_length_scale=min_length_scale,
        )
        self.video_combiner = VideoCombiner(ffmpeg_path=ffmpeg_path)
        self.srt_parser = SRTParser()

    @staticmethod
    def _deploy_file(src_path: Path, dst_path: Path, max_retries: int = 3) -> None:
        """別ファイルシステム間でも安全に最終配置する。"""

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = dst_path.with_suffix(dst_path.suffix + ".part")

        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                if part_path.exists():
                    part_path.unlink()

                shutil.copy2(src_path, part_path)
                os.replace(part_path, dst_path)
                return
            except Exception as e:
                last_error = e
                if part_path.exists():
                    try:
                        part_path.unlink()
                    except Exception:
                        pass
                if attempt < max_retries:
                    time.sleep(0.5 * attempt)

        raise RuntimeError(f"最終ファイル配置に失敗しました: {dst_path}") from last_error
    
    def create_dubbed_video(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        temp_audio_path: Optional[str] = None,
        work_dir: Optional[str] = None,
        style: str = "Neutral",
        style_weight: float = 1.0,
        overlay: bool = False,
        audio_volume: float = 1.0,
        original_volume: float = 0.3,
        intro_duration: float = 0.0,
    ) -> bool:
        """
        吹き替え動画を作成
        
        Args:
            video_path: 元の動画ファイルパス
            srt_path: SRTファイルパス
            output_path: 出力動画ファイルパス
            temp_audio_path: 一時音声ファイルパス(Noneなら自動生成)
            style: 感情スタイル
            style_weight: スタイルの強さ
            overlay: Trueなら元の音声に重ねる、Falseなら置き換える（デフォルト: 置き替え）
            audio_volume: 生成音声の音量
            original_volume: 元の音声の音量(overlayがTrueの場合のみ)
            intro_duration: イントロ部分のみ元の音声を重ねる時間(秒)。0.0なら無効
            
        Returns:
            成功したらTrue
        """
        staged = self.create_dubbed_video_to_staging(
            video_path=video_path,
            srt_path=srt_path,
            output_path=output_path,
            temp_audio_path=temp_audio_path,
            work_dir=work_dir,
            style=style,
            style_weight=style_weight,
            overlay=overlay,
            audio_volume=audio_volume,
            original_volume=original_volume,
            intro_duration=intro_duration,
        )
        self.deploy_staged_output(staged)
        print(f"✅ 吹き替え動画作成完了: {staged.final_output_path}")
        return True

    def create_dubbed_video_to_staging(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        temp_audio_path: Optional[str] = None,
        work_dir: Optional[str] = None,
        style: str = "Neutral",
        style_weight: float = 1.0,
        overlay: bool = False,
        audio_volume: float = 1.0,
        original_volume: float = 0.3,
        intro_duration: float = 0.0,
    ) -> StagedDubResult:
        """GPU推論と動画合成までを実行し、成果物をローカル作業領域へ出力する。"""

        final_output_path = Path(output_path)
        staging_root = Path(work_dir) if work_dir else self.work_root_dir
        staging_root.mkdir(parents=True, exist_ok=True)

        work_id = f"{final_output_path.stem}_{uuid4().hex}"
        staging_video_path = staging_root / f"{work_id}{final_output_path.suffix}"
        staging_srt_path = staging_video_path.with_suffix('.srt')

        if temp_audio_path is None:
            temp_audio_path = str(staging_root / f"{work_id}.temp.wav")

        temp_audio = Path(temp_audio_path)

        try:
            print(f"SRTファイルを解析中: {srt_path}")
            entries = self.srt_parser.parse_srt(srt_path)
            print(f"{len(entries)}個の字幕エントリを検出")

            print(f"動画の長さを取得中: {video_path}")
            video_duration = self.video_combiner.get_video_duration(video_path)
            print(f"動画の長さ: {video_duration:.2f}秒")

            print("音声を生成中...")
            success, _ = self.audio_generator.generate_audio_from_srt(
                entries=entries,
                output_path=temp_audio_path,
                video_duration=video_duration,
                tolerance_seconds=self.tolerance_seconds,
                style=style,
                style_weight=style_weight,
            )

            if not success:
                print("許容範囲を超えています。グローバル話速調整で再生成中...")
                success = self.audio_generator.regenerate_with_global_adjustment(
                    entries=entries,
                    output_path=temp_audio_path,
                    video_duration=video_duration,
                    tolerance_seconds=self.tolerance_seconds,
                    style=style,
                    style_weight=style_weight,
                )
                if not success:
                    print("警告: 最速でも許容範囲内に収まりませんでした。そのまま結合します。")

            print("動画と音声を結合中...")
            self.video_combiner.combine_audio(
                video_path=video_path,
                audio_path=temp_audio_path,
                output_path=str(staging_video_path),
                overlay=overlay,
                audio_volume=audio_volume,
                original_volume=original_volume,
                intro_duration=intro_duration,
            )

            try:
                shutil.copy2(srt_path, staging_srt_path)
            except Exception as e:
                print(f"⚠️ 字幕ファイルのステージングに失敗: {e}")

            return StagedDubResult(
                final_output_path=final_output_path,
                staging_video_path=staging_video_path,
                staging_srt_path=staging_srt_path,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}")
            for path in (staging_video_path, staging_srt_path):
                if path.exists():
                    try:
                        path.unlink()
                    except Exception:
                        pass
            raise
        finally:
            if temp_audio_path and temp_audio.exists():
                try:
                    temp_audio.unlink()
                    print(f"一時ファイル削除: {temp_audio}")
                except Exception as e:
                    print(f"一時ファイル削除失敗: {e}")

    def deploy_staged_output(self, staged: StagedDubResult) -> None:
        """ローカル作業領域の成果物を最終保存先へ配置する。"""

        try:
            self._deploy_file(staged.staging_video_path, staged.final_output_path)
            print(f"動画ファイルを配置: {staged.final_output_path}")

            final_srt_path = staged.final_output_path.with_suffix('.srt')
            if staged.staging_srt_path.exists():
                self._deploy_file(staged.staging_srt_path, final_srt_path)
                print(f"字幕ファイルを配置: {final_srt_path}")
        finally:
            self.cleanup_staged_output(staged)

    def cleanup_staged_output(self, staged: StagedDubResult) -> None:
        """ステージング成果物を安全に削除する。"""

        for path in (staged.staging_video_path, staged.staging_srt_path):
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
