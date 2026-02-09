"""
音声生成モジュール

TTSで字幕から音声を生成し、タイミングに合わせて1つのWAVファイルを作成します。

重要なポリシー:
- 音声カットは一切禁止です
- 音声が長すぎる場合は話速を調整して再生成します
"""

import gc
import os
import wave
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

from style_bert_vits2.tts_model import TTSModel
from .srt_parser import SRTEntry
from .text_preprocessor import get_preprocessor


class AudioGenerator:
    """
    TTS音声生成クラス
    
    字幕に基づいて音声を生成し、無音を挟んで1つのWAVファイルを作成します。
    音声が長すぎる場合は話速を調整して再生成します。
    """
    
    def __init__(
        self,
        tts_model: TTSModel,
        sample_rate: int = 44100,
        min_length_scale: float = 0.5,  # 最速2倍速
        initial_length_scale: float = 1.0,
        use_preprocessor: bool = True,  # テキスト前処理を使用（英語→カタカナ）
    ):
        """
        Args:
            tts_model: Style-Bert-VITS2のTTSモデル
            sample_rate: サンプリングレート
            min_length_scale: 最小length_scale(これ以上速くしない)
            initial_length_scale: 初期length_scale
            use_preprocessor: テキスト前処理を使用（英語→カタカナ）
        """
        self.tts_model = tts_model
        self.sample_rate = sample_rate
        self.min_length_scale = min_length_scale
        self.initial_length_scale = initial_length_scale
        self.use_preprocessor = use_preprocessor
        
        # テキスト前処理インスタンス
        if use_preprocessor:
            self.preprocessor = get_preprocessor()
        else:
            self.preprocessor = None
    
    def generate_audio_for_entry(
        self,
        entry: SRTEntry,
        length_scale: float = 1.0,
        style: str = "Neutral",
        style_weight: float = 1.0,
    ) -> np.ndarray:
        """
        1つの字幕エントリに対して音声を生成
        
        音声が字幕時間より長い場合、自動的に話速を調整して再生成します。
        
        Args:
            entry: SRTEntry
            length_scale: 話速(1.0が標準、小さいほど速い)
            style: 感情スタイル
            style_weight: スタイルの強さ
            
        Returns:
            音声データ(numpy配列)
        """
        current_scale = length_scale
        
        # テキスト前処理（英語→カタカナ、最初に1回だけ実行）
        text_to_speak = entry.text
        if self.preprocessor:
            text_to_speak = self.preprocessor.preprocess(entry.text)
            if text_to_speak != entry.text:
                print(f"  [{entry.index}] テキスト変換(英語→カタカナ): {entry.text} → {text_to_speak}")
        
        attempt = 0  # 速度調整の試行回数をカウント
        while current_scale >= self.min_length_scale:
            attempt += 1
            
            # TTS生成（戻り値は(sampling_rate, audio)のタプル）
            sr, audio = self.tts_model.infer(
                text=text_to_speak,
                language="JP",
                speaker_id=0,
                style=style,
                style_weight=style_weight,
                length=current_scale,
            )
            
            # サンプリングレートを更新（初回のみ）
            if hasattr(self, '_actual_sample_rate') is False:
                self._actual_sample_rate = sr
            
            # 音声データを1次元配列に変換（ステレオの場合はモノラルに）
            if audio.ndim > 1:
                audio = audio.flatten()
            
            # int16からfloat32に正規化（-1.0 ~ 1.0）
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            else:
                audio = audio.astype(np.float32)
            
            # 音声の長さを計算
            audio_duration = len(audio) / sr
            
            # 字幕時間内に収まるかチェック
            if audio_duration <= entry.duration:
                if attempt > 1:
                    print(f"    → 速度調整完了: {attempt}回目で収まりました (speed={current_scale:.3f})")
                return audio
            
            # 長すぎる場合は話速を上げる(length_scaleを下げる)
            if attempt == 1:
                print(f"    速度調整中... (音声:{audio_duration:.2f}秒 > 字幕:{entry.duration:.2f}秒)")
            current_scale -= 0.05
        
        # 最速でも収まらない場合は警告して最速版を返す
        print(f"警告: 字幕{entry.index}の音声が最速でも収まりません。"
              f"音声:{audio_duration:.2f}秒 vs 字幕:{entry.duration:.2f}秒")
        return audio
    
    def generate_silence(self, duration: float) -> np.ndarray:
        """
        無音を生成
        
        Args:
            duration: 無音の長さ(秒)
            
        Returns:
            無音データ(numpy配列)
        """
        samples = int(duration * self.sample_rate)
        return np.zeros(samples, dtype=np.float32)
    
    def generate_audio_from_srt(
        self,
        entries: List[SRTEntry],
        output_path: str,
        video_duration: float,
        tolerance_seconds: float = 60.0,
        style: str = "Neutral",
        style_weight: float = 1.0,
    ) -> Tuple[bool, float]:
        """
        SRTエントリリストから1つのWAVファイルを生成
        
        【重要】キュー方式(Queue方式):
        - 理想: 各音声はSRTの開始時刻通りに再生したい
        - 現実: 話者の速度に完全に合わせるのは困難
        - 妥協案: A音声が長引いてB音声の開始時刻に間に合わない場合、B音声はキューに入り遅れて再生開始
        - 音声カットは一切なし、全ての音声を順次再生(無音期間で時間を相殺)
        - 例: A音声が3秒超過 → B音声の開始が3秒遅延 → C音声以降も影響を受ける可能性
        
        各字幕に対して音声を生成し、タイミングに合わせて無音を挿入します。
        メモリ効率のため、生成した音声は即座にWAVファイルへストリーミング書き込みします。
        最終的な音声時間と動画時間を比較し、許容範囲を超える場合は再生成が必要と判定します。
        
        Args:
            entries: SRTEntryのリスト
            output_path: 出力WAVファイルパス
            video_duration: 元の動画の長さ(秒)
            tolerance_seconds: 許容超過時間(秒)
            style: 感情スタイル
            style_weight: スタイルの強さ
            
        Returns:
            (成功フラグ, 実際の音声時間)
            成功フラグ: 許容範囲内に収まればTrue
        """
        current_time = 0.0  # 実際の音声再生時刻(遅延を考慮)
        length_scale = self.initial_length_scale
        total_samples = 0
        
        # 出力ディレクトリを作成
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        
        # WAVファイルへストリーミング書き込み（メモリ効率改善）
        # 全音声をメモリに蓄積せず、生成した音声を即座に書き込む
        actual_sr = getattr(self, '_actual_sample_rate', self.sample_rate)
        
        with wave.open(output_path, 'w') as wav_file:
            wav_file.setnchannels(1)    # モノラル
            wav_file.setsampwidth(2)    # 16bit
            wav_file.setframerate(actual_sr)
            
            for i, entry in enumerate(entries):
                # 前の字幕からのギャップを無音で埋める
                # ただし、前の音声が超過していた場合は無音なし(キュー方式)
                if entry.start_time > current_time:
                    silence_duration = entry.start_time - current_time
                    silence = self.generate_silence(silence_duration)
                    self._write_audio_chunk(wav_file, silence)
                    total_samples += len(silence)
                    current_time = entry.start_time
                # else: current_time >= entry.start_time の場合
                #       → 前の音声が超過しているので、キューに入り無音なしで次の音声を続ける
                
                # 音声生成(自動話速調整あり)
                audio = self.generate_audio_for_entry(
                    entry,
                    length_scale=length_scale,
                    style=style,
                    style_weight=style_weight,
                )
                
                # 初回推論後にサンプリングレートを確認・更新
                new_sr = getattr(self, '_actual_sample_rate', self.sample_rate)
                if new_sr != actual_sr and i == 0:
                    actual_sr = new_sr
                    wav_file.setframerate(actual_sr)
                
                # WAVファイルに直接書き込み（メモリ解放）
                self._write_audio_chunk(wav_file, audio)
                total_samples += len(audio)
                
                # 現在時刻を更新(音声の長さ分進める)
                audio_duration = len(audio) / actual_sr
                current_time += audio_duration
                
                # 遅延が発生している場合は警告
                if current_time > entry.end_time:
                    delay = current_time - entry.end_time
                    print(f"  字幕{entry.index}: 音声が{delay:.2f}秒超過(次の音声が遅延します)")
                
                # 定期的にメモリを解放（長い動画のOOM防止）
                del audio
                if (i + 1) % 50 == 0:
                    gc.collect()
                    if _HAS_TORCH and torch.cuda.is_available():
                        torch.cuda.empty_cache()
        
        # 結果判定
        total_duration = total_samples / actual_sr
        
        # 許容範囲チェック
        overflow = total_duration - video_duration
        success = overflow <= tolerance_seconds
        
        if not success:
            print(f"音声が動画より{overflow:.2f}秒長すぎます(許容範囲:{tolerance_seconds}秒)")
        else:
            print(f"音声生成完了: {total_duration:.2f}秒(動画:{video_duration:.2f}秒、超過:{overflow:.2f}秒)")
        
        return success, total_duration
    
    def regenerate_with_global_adjustment(
        self,
        entries: List[SRTEntry],
        output_path: str,
        video_duration: float,
        tolerance_seconds: float = 60.0,
        style: str = "Neutral",
        style_weight: float = 1.0,
        max_iterations: int = 5,
    ) -> bool:
        """
        グローバルな話速調整で再生成
        
        全体の音声時間が許容範囲内に収まるまで、段階的に話速を調整します。
        
        Args:
            entries: SRTEntryのリスト
            output_path: 出力WAVファイルパス
            video_duration: 元の動画の長さ(秒)
            tolerance_seconds: 許容超過時間(秒)
            style: 感情スタイル
            style_weight: スタイルの強さ
            max_iterations: 最大試行回数
            
        Returns:
            成功フラグ
        """
        for i in range(max_iterations):
            # length_scaleを徐々に下げる
            length_scale = self.initial_length_scale - (i * 0.1)
            
            if length_scale < self.min_length_scale:
                print(f"最速でも許容範囲内に収まりません")
                return False
            
            print(f"試行{i+1}: length_scale={length_scale:.2f}で再生成中...")
            
            # 再生成
            self.initial_length_scale = length_scale
            success, total_duration = self.generate_audio_from_srt(
                entries=entries,
                output_path=output_path,
                video_duration=video_duration,
                tolerance_seconds=tolerance_seconds,
                style=style,
                style_weight=style_weight,
            )
            
            if success:
                print(f"成功: length_scale={length_scale:.2f}で許容範囲内に収まりました")
                return True
        
        return False
    
    def _write_audio_chunk(self, wav_file, audio: np.ndarray):
        """
        音声チャンクをWAVファイルに直接書き込む（メモリ効率改善）
        
        各字幕の音声を個別にint16変換して書き込むため、
        全体を一度にメモリに保持する必要がありません。
        
        Args:
            wav_file: wave.Wave_writeオブジェクト
            audio: 音声データ(float32, -1.0~1.0)
        """
        audio_int16 = (audio * 32767).astype(np.int16)
        wav_file.writeframes(audio_int16.tobytes())
    
    def _save_wav(self, path: str, audio: np.ndarray):
        """
        WAVファイル保存
        
        Args:
            path: 保存先パス
            audio: 音声データ(float32, -1.0~1.0)
        """
        # int16に変換
        audio_int16 = (audio * 32767).astype(np.int16)
        
        # ディレクトリ作成
        path_dir = os.path.dirname(path)
        if path_dir:
            os.makedirs(path_dir, exist_ok=True)
        
        # 実際のサンプリングレートを使用
        actual_sr = getattr(self, '_actual_sample_rate', self.sample_rate)
        
        # WAV保存
        with wave.open(path, 'w') as wav_file:
            wav_file.setnchannels(1)  # モノラル
            wav_file.setsampwidth(2)  # 16bit
            wav_file.setframerate(actual_sr)
            wav_file.writeframes(audio_int16.tobytes())
