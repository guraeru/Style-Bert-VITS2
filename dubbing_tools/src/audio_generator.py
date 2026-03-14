"""
音声生成モジュール

TTSで字幕から音声を生成し、タイミングに合わせて1つのWAVファイルを作成します。

重要なポリシー:
- 音声カットは一切禁止です
- 音声が長すぎる場合は話速を調整して再生成します
"""

import gc
import os
import re
import wave
import numpy as np
from typing import List, Tuple, Optional, Any
from pathlib import Path

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

from style_bert_vits2.tts_model import TTSModel
from style_bert_vits2.constants import Languages
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
        max_length_scale: float = 1.08,
        use_preprocessor: bool = True,  # テキスト前処理を使用（英語→カタカナ）
        max_entry_adjustment_attempts: int = 2,
        fit_margin_ratio: float = 0.02,
    ):
        """
        Args:
            tts_model: Style-Bert-VITS2のTTSモデル
            sample_rate: サンプリングレート
            min_length_scale: 最小length_scale(これ以上速くしない)
            initial_length_scale: 初期length_scale
            max_length_scale: 最大length_scale（大きいほど遅くなる。自然さのため低め推奨）
            use_preprocessor: テキスト前処理を使用（英語→カタカナ）
            max_entry_adjustment_attempts: 1字幕あたりの最大推論回数
            fit_margin_ratio: 字幕尺に対する許容超過率（0.02=2%）
        """
        self.tts_model = tts_model
        self.sample_rate = sample_rate
        self.min_length_scale = min_length_scale
        self.max_length_scale = max(min_length_scale, max_length_scale)
        self.initial_length_scale = max(self.min_length_scale, min(self.max_length_scale, initial_length_scale))
        self.use_preprocessor = use_preprocessor
        self.max_entry_adjustment_attempts = max(1, max_entry_adjustment_attempts)
        self.fit_margin_ratio = max(0.0, fit_margin_ratio)

        # 話速予測モデル（軽量なオンライン学習）
        # duration_at_length=1 ≒ sec_per_unit * text_units
        self._sec_per_unit_ema = 0.085
        self._sec_per_unit_alpha = 0.2
        self._duration_model_ready = False
        
        # テキスト前処理インスタンス
        self.preprocessor: Optional[Any] = None
        if use_preprocessor:
            self.preprocessor = get_preprocessor()  # type: ignore[assignment]

    def _text_units(self, text: str) -> float:
        """文字種ごとの重み付き長さを計算する。"""
        text = text.strip()
        if not text:
            return 1.0

        units = 0.0
        for ch in text:
            code = ord(ch)
            if ch.isspace():
                continue
            # 句読点・記号は短く読み飛ばしやすい
            if re.match(r"[\.,!?;:、。！？・…ー\-()\[\]{}'\"“”‘’]", ch):
                units += 0.35
                continue
            # 日本語文字
            if (
                0x3040 <= code <= 0x309F  # ひらがな
                or 0x30A0 <= code <= 0x30FF  # カタカナ
                or 0x4E00 <= code <= 0x9FFF  # CJK統合漢字
                or 0x3400 <= code <= 0x4DBF  # CJK拡張A
            ):
                units += 1.0
                continue
            # 英数字は日本語1文字より短くなりやすい
            if ch.isascii() and ch.isalnum():
                units += 0.55
                continue
            units += 0.8

        return max(units, 1.0)

    def _predict_length_scale(self, target_duration: float, text_units: float, fallback_scale: float) -> float:
        """目標字幕尺に収まる length_scale を予測する。"""
        predicted_at_scale_1 = self._sec_per_unit_ema * max(text_units, 1e-6)
        if predicted_at_scale_1 <= 1e-6:
            return self._clamp_length_scale(fallback_scale)

        # duration は length_scale にほぼ比例する前提で逆算
        raw_scale = target_duration / predicted_at_scale_1
        # 字幕尺が長くても不自然に遅くしすぎない（余剰時間は無音で吸収する）
        if raw_scale > 1.0:
            raw_scale = 1.0 + (raw_scale - 1.0) * 0.15
        # わずかに速め側へ倒して超過を減らす
        safety = 0.97
        return self._clamp_length_scale(raw_scale * safety)

    def _clamp_length_scale(self, value: float) -> float:
        return max(self.min_length_scale, min(self.max_length_scale, value))

    def _update_duration_model(self, text_units: float, audio_duration: float, used_scale: float) -> None:
        """推論結果から話速予測モデルをオンライン更新する。"""
        if text_units <= 1e-6 or used_scale <= 1e-6:
            return

        normalized_duration = audio_duration / used_scale
        sec_per_unit = normalized_duration / text_units

        # 異常値は学習に入れない
        if not (0.01 <= sec_per_unit <= 1.5):
            return

        if not self._duration_model_ready:
            self._sec_per_unit_ema = sec_per_unit
            self._duration_model_ready = True
            return

        alpha = self._sec_per_unit_alpha
        self._sec_per_unit_ema = (1.0 - alpha) * self._sec_per_unit_ema + alpha * sec_per_unit

    def _infer_with_scale(
        self,
        text_to_speak: str,
        length_scale: float,
        style: str,
        style_weight: float,
    ) -> Tuple[int, np.ndarray]:
        """指定 speed で1回だけTTS推論する。"""
        sr, audio = self.tts_model.infer(
            text=text_to_speak,
            language=Languages.JP,  # type: ignore[arg-type]
            speaker_id=0,
            style=style,
            style_weight=style_weight,
            length=length_scale,
        )

        if hasattr(self, '_actual_sample_rate') is False:
            self._actual_sample_rate = sr

        if audio.ndim > 1:
            audio = audio.flatten()

        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32)

        return sr, audio
    
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
        # テキスト前処理（英語→カタカナ、最初に1回だけ実行）
        text_to_speak = entry.text
        if self.preprocessor:
            text_to_speak = self.preprocessor.preprocess(entry.text)
            if text_to_speak != entry.text:
                print(f"  [{entry.index}] テキスト変換(英語→カタカナ): {entry.text} → {text_to_speak}")

        target_duration = max(entry.duration, 0.05)
        text_units = self._text_units(text_to_speak)

        # 1回目は予測速度で生成し、必要なら比例制御で1回だけ補正
        current_scale = self._predict_length_scale(
            target_duration=target_duration,
            text_units=text_units,
            fallback_scale=length_scale,
        )

        best_audio: Optional[np.ndarray] = None
        best_duration = 0.0
        best_scale = current_scale
        best_score = float("inf")

        for attempt in range(1, self.max_entry_adjustment_attempts + 1):
            sr, audio = self._infer_with_scale(
                text_to_speak=text_to_speak,
                length_scale=current_scale,
                style=style,
                style_weight=style_weight,
            )
            audio_duration = len(audio) / sr

            overflow = audio_duration - target_duration
            # 超過は強くペナルティし、収まる候補を優先
            score = abs(overflow) + (5.0 if overflow > target_duration * self.fit_margin_ratio else 0.0)
            if score < best_score:
                if best_audio is not None:
                    del best_audio
                best_audio = audio
                best_duration = audio_duration
                best_scale = current_scale
                best_score = score
            else:
                del audio

            # 収まったら打ち切り
            if overflow <= target_duration * self.fit_margin_ratio:
                if attempt > 1:
                    print(f"    → 速度調整完了: {attempt}回目で収まりました (speed={current_scale:.3f})")
                break

            if attempt == 1:
                print(f"    速度補正中... (音声:{audio_duration:.2f}秒 > 字幕:{target_duration:.2f}秒)")

            if attempt >= self.max_entry_adjustment_attempts:
                break

            # 比例制御: duration ∝ length_scale を仮定して次の scale を逆算
            ratio = target_duration / max(audio_duration, 1e-6)
            next_scale = self._clamp_length_scale(current_scale * ratio * 0.98)
            if abs(next_scale - current_scale) < 0.01:
                break
            current_scale = next_scale

        if best_audio is None:
            raise RuntimeError(f"字幕{entry.index}の音声生成に失敗しました")

        if best_duration > target_duration * (1.0 + self.fit_margin_ratio):
            print(
                f"警告: 字幕{entry.index}の音声が尺超過です。"
                f"音声:{best_duration:.2f}秒 vs 字幕:{target_duration:.2f}秒 (speed={best_scale:.3f})"
            )

        self._update_duration_model(
            text_units=text_units,
            audio_duration=best_duration,
            used_scale=best_scale,
        )
        return best_audio
    
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
        original_initial_scale = self.initial_length_scale
        target_total_duration = video_duration + tolerance_seconds
        current_scale = original_initial_scale

        try:
            for i in range(max_iterations):
                current_scale = self._clamp_length_scale(current_scale)
                if current_scale <= self.min_length_scale and i > 0:
                    print("最速でも許容範囲内に収まりません")
                    return False

                print(f"試行{i+1}: length_scale={current_scale:.3f}で再生成中...")

                self.initial_length_scale = current_scale
                success, total_duration = self.generate_audio_from_srt(
                    entries=entries,
                    output_path=output_path,
                    video_duration=video_duration,
                    tolerance_seconds=tolerance_seconds,
                    style=style,
                    style_weight=style_weight,
                )

                if success:
                    print(f"成功: length_scale={current_scale:.3f}で許容範囲内に収まりました")
                    return True

                # 全体長に対する比率で次回の length_scale を直接推定
                ratio = target_total_duration / max(total_duration, 1e-6)
                next_scale = self._clamp_length_scale(current_scale * ratio * 0.98)
                if abs(next_scale - current_scale) < 0.01:
                    print("これ以上の改善が見込めないため再生成を終了します")
                    return False
                current_scale = next_scale

            return False
        finally:
            # 次ファイルへの副作用を避ける
            self.initial_length_scale = original_initial_scale
    
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
