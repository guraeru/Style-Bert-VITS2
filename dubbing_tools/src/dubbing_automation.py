"""
吹き替え自動化メインモジュール

SRT解析、音声生成、動画結合を統合したメインクラスです。
"""

import os
from pathlib import Path
from typing import Optional

from style_bert_vits2.tts_model import TTSModel
from .srt_parser import SRTParser
from .audio_generator import AudioGenerator
from .video_combiner import VideoCombiner


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
    
    def create_dubbed_video(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        temp_audio_path: Optional[str] = None,
        style: str = "Neutral",
        style_weight: float = 1.0,
        overlay: bool = False,
        audio_volume: float = 1.0,
        original_volume: float = 0.3,
        intro_only: bool = False,
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
            intro_only: Trueならイントロ部分(最初の字幕開始まで)のみ元の音声を重ねる
            
        Returns:
            成功したらTrue
        """
        # 一時音声ファイルパス生成
        if temp_audio_path is None:
            temp_audio_path = str(Path(output_path).with_suffix('.temp.wav'))
        
        try:
            # ステップ1: SRT解析
            print(f"SRTファイルを解析中: {srt_path}")
            entries = self.srt_parser.parse_srt(srt_path)
            print(f"{len(entries)}個の字幕エントリを検出")
            
            # ステップ2: 動画の長さを取得
            print(f"動画の長さを取得中: {video_path}")
            video_duration = self.video_combiner.get_video_duration(video_path)
            print(f"動画の長さ: {video_duration:.2f}秒")
            
            # ステップ3: 音声生成(自動話速調整あり)
            print(f"音声を生成中...")
            success, audio_duration = self.audio_generator.generate_audio_from_srt(
                entries=entries,
                output_path=temp_audio_path,
                video_duration=video_duration,
                tolerance_seconds=self.tolerance_seconds,
                style=style,
                style_weight=style_weight,
            )
            
            # ステップ4: 許容範囲を超えている場合は再生成
            if not success:
                print(f"許容範囲を超えています。グローバル話速調整で再生成中...")
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
            
            # ステップ5: 動画と音声を結合
            print(f"動画と音声を結合中...")
            
            # イントロ部分のみ元の音声を重ねる場合、最初の字幕開始時刻を取得
            intro_duration = 0.0
            if intro_only and overlay and len(entries) > 0:
                intro_duration = entries[0].start_time
                print(f"イントロ部分のみ元の音声を重ねます(0秒 ~ {intro_duration:.2f}秒)")
            
            self.video_combiner.combine_audio(
                video_path=video_path,
                audio_path=temp_audio_path,
                output_path=output_path,
                overlay=overlay,
                audio_volume=audio_volume,
                original_volume=original_volume,
                intro_duration=intro_duration,
            )
            
            # ステップ6: SRTファイルをそのままコピー
            output_srt_path = str(Path(output_path).with_suffix('.srt'))
            try:
                import shutil
                shutil.copy2(srt_path, output_srt_path)
                print(f"字幕ファイルをコピー: {output_srt_path}")
            except Exception as e:
                print(f"⚠️ 字幕ファイルのコピーに失敗: {e}")
            
            print(f"✅ 吹き替え動画作成完了: {output_path}")
            return True
            
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}")
            raise
        finally:
            # 一時ファイル削除
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                    print(f"一時ファイル削除: {temp_audio_path}")
                except Exception as e:
                    print(f"一時ファイル削除失敗: {e}")
