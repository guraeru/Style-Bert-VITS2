"""
動画結合モジュール

ffmpegを使用して動画と音声を結合します。
ビデオストリームはコピー、音声のみエンコードするため高速です。

設計方針:
- subprocess はリスト形式 + shell=False（UNCパス・日本語パスに安全）
- overlay/introモードでは 2パス方式 を使用:
  Pass 1: 元動画の音声を -ac 2 -ar 44100 で強制デコード → クリーンWAV
           → AACの壊れたフレーム（wrong sample count, 異常チャンネル数等）を
             デコーダレベルで吸収し、出力は常に一定フォーマット
  Pass 2: クリーンWAV同士を amix でミキシング → 動画と結合
           → 両入力が同一フォーマットのため filter reinit エラーが起きない
- amix は normalize=0 + dropout_transition=0 で安定動作
"""

import json
import subprocess
import os
from loguru import logger

# ── ミキシングパラメータ ──
_MIX_SR = 44100
_MIX_CHANNELS = 2
# 生成音声(TTS)向け正規化: 正常なWAVなので aformat のみ
_NORM_GEN = f"aformat=sample_fmts=fltp:sample_rates={_MIX_SR}:channel_layouts=stereo"
# amix 共通オプション
_AMIX = "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0"


class VideoCombiner:
    """
    動画と音声を結合するクラス

    ffmpegを使用して、元の動画に生成した音声を重ねます。
    overlay/intro モードでは壊れた音声トラックにも耐性を持つ2パス方式を使用します。
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path

    # ── 内部ユーティリティ ──

    def _probe_has_audio(self, video_path: str) -> bool:
        """動画ファイルに音声トラックが存在するか確認する。"""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=index",
            "-of", "json",
            video_path,
        ]
        try:
            r = subprocess.run(
                cmd, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
            data = json.loads(r.stdout)
            return len(data.get("streams", [])) > 0
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return False

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        """ffmpeg を実行し、失敗時は stderr 末尾をログ出力して例外を送出する。"""
        try:
            subprocess.run(
                cmd, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpegエラー (exit={e.returncode})")
            if e.stderr:
                for line in e.stderr.rstrip().splitlines()[-15:]:
                    logger.error(f"  {line}")
            raise

    def _extract_clean_audio(
        self, video_path: str, output_wav: str,
        duration_limit: float = 0.0,
    ) -> bool:
        """
        元動画の音声を正規化されたWAVファイルとして抽出する。

        -ac 2 -ar 44100 -c:a pcm_s16le で強制再エンコードするため、
        壊れたAACフレーム（異常チャンネル数、wrong sample count等）が
        あっても出力は常に 44100Hz stereo PCM になる。

        Returns:
            抽出成功ならTrue。失敗しても部分的なWAVが使える場合はTrue。
        """
        cmd = [
            self.ffmpeg_path,
            "-fflags", "+discardcorrupt+genpts+igndts",
        ]
        if duration_limit > 0:
            cmd += ["-t", str(duration_limit)]
        cmd += [
            "-i", video_path,
            "-vn",
            "-c:a", "pcm_s16le",
            "-ar", str(_MIX_SR),
            "-ac", str(_MIX_CHANNELS),
            "-y", output_wav,
        ]

        result = subprocess.run(
            cmd, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            logger.warning("元音声の抽出でデコードエラー発生（部分出力を確認中）")

        # WAV header (44B) より大きければ有効な音声データがある
        return os.path.exists(output_wav) and os.path.getsize(output_wav) > 44

    # ── Public API ──

    def combine_audio(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        overlay: bool = False,
        audio_volume: float = 1.0,
        original_volume: float = 0.3,
        intro_duration: float = 0.0,
    ) -> bool:
        """
        動画と音声を結合

        ビデオストリームをコピーし、音声のみ結合します。

        overlay/intro モードでは2パス方式で処理:
          Pass 1: 元音声を -ac 2 -ar 44100 でクリーンWAVに抽出
          Pass 2: クリーンWAV同士をamixでミキシングし、動画と結合
        これにより壊れたAACストリームでも安全に処理できます。

        overlay=True で元動画に音声トラックがない場合は自動的に
        replace モード（音声置き換え）にフォールバックします。

        Args:
            video_path: 元の動画ファイルパス
            audio_path: 生成した音声ファイルパス(WAV)
            output_path: 出力動画ファイルパス
            overlay: Trueなら元の音声に重ねる、Falseなら置き換える
            audio_volume: 生成音声の音量(0.0~)
            original_volume: 元の音声の音量(0.0~, overlayがTrueの場合のみ)
            intro_duration: イントロの長さ(秒)。元音声を重ねてから生成音声に切り替える

        Returns:
            成功したらTrue

        Raises:
            FileNotFoundError: 入力ファイルが見つからない場合
            subprocess.CalledProcessError: ffmpegの実行に失敗した場合
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_path}")

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # overlay要求だが音声トラックがない or 抽出失敗 → replace にフォールバック
        if overlay and not self._probe_has_audio(video_path):
            logger.warning("元動画に音声トラックがないため、生成音声のみで出力します")
            overlay = False

        logger.info(f"動画結合中: {output_path}")

        if overlay:
            self._combine_with_overlay(
                video_path, audio_path, output_path,
                audio_volume, original_volume, intro_duration,
            )
        else:
            self._combine_replace(video_path, audio_path, output_path)

        logger.info(f"動画結合完了: {output_path}")
        return True

    def _combine_replace(
        self, video_path: str, audio_path: str, output_path: str,
    ) -> None:
        """音声を完全に置き換え（フィルタ不要、単純マッピング）。"""
        cmd = [
            self.ffmpeg_path,
            "-fflags", "+genpts+igndts",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac",
            "-y", output_path,
        ]
        self._run_ffmpeg(cmd)

    def _combine_with_overlay(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        audio_volume: float,
        original_volume: float,
        intro_duration: float,
    ) -> None:
        """
        2パス方式で元音声と生成音声をミキシングして動画と結合する。

        Pass 1: 元音声をクリーンWAV (44100Hz stereo PCM) として抽出
        Pass 2: クリーンWAV + 生成WAV → amix → 動画結合
        """
        # 一時WAVのパス（出力先と同じディレクトリに生成）
        orig_wav = output_path + f".orig_{os.getpid()}.wav"

        try:
            # --- Pass 1: 元音声の抽出 ---
            # introモードなら必要な長さ+1秒だけ抽出（高速）
            extract_duration = (intro_duration + 1.0) if intro_duration > 0 else 0.0

            logger.info("Pass 1/2: 元音声を抽出・正規化中...")
            extracted = self._extract_clean_audio(
                video_path, orig_wav, duration_limit=extract_duration,
            )

            if not extracted:
                logger.warning("元音声の抽出に失敗。生成音声のみで出力します")
                self._combine_replace(video_path, audio_path, output_path)
                return

            # --- Pass 2: ミキシング + 動画結合 ---
            logger.info("Pass 2/2: ミキシング・動画結合中...")

            if intro_duration > 0:
                fade_d = 0.2
                fc = (
                    f"[1:a]{_NORM_GEN},afade=t=out:st={intro_duration}:d={fade_d}[orig];"
                    f"[2:a]{_NORM_GEN},volume={audio_volume}[gen];"
                    f"[orig][gen]{_AMIX}[aout]"
                )
            else:
                fc = (
                    f"[1:a]{_NORM_GEN},volume={original_volume}[a1];"
                    f"[2:a]{_NORM_GEN},volume={audio_volume}[a2];"
                    f"[a1][a2]{_AMIX}[aout]"
                )

            cmd = [
                self.ffmpeg_path,
                "-fflags", "+genpts+igndts",
                "-i", video_path,       # 0: video stream のみ使用
                "-i", orig_wav,          # 1: クリーン化された元音声
                "-i", audio_path,        # 2: TTS生成音声
                "-filter_complex", fc,
                "-map", "0:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac",
                "-y", output_path,
            ]
            self._run_ffmpeg(cmd)

        finally:
            if os.path.exists(orig_wav):
                try:
                    os.unlink(orig_wav)
                except OSError:
                    pass

    def get_video_duration(self, video_path: str) -> float:
        """
        動画の長さを取得

        Raises:
            FileNotFoundError: ファイルが見つからない場合
            ValueError: 長さを取得できない場合
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]

        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            raise ValueError(f"動画の長さを取得できません: {e}")
