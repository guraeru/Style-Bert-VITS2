"""
Style-Bert-VITS2 吹き替え自動化ツール

このパッケージは動画の自動吹き替えを行うツールです。
SRTファイルから字幕を読み取り、TTSで音声を生成し、元の動画と結合します。

重要なポリシー:
- 音声カットは一切行いません
- 音声が長すぎる場合は話速(length_scale)を調整して再生成します
- 許容範囲(デフォルト60秒)を超える場合のみ調整を行います

キュー方式(Queue方式):
- 理想: 各音声はSRTの開始時刻通りに再生したいが、話者速度に完全に合わせるのは非現実的
- 妥協案: A音声が長引いてB音声の開始時刻に間に合わない場合、B音声はキュー待ちで遅延再生
- 音声の重複や削除は一切なし、全て順次再生(無音期間で相殺)
"""

from .srt_parser import SRTEntry, SRTParser
from .audio_generator import AudioGenerator
from .video_combiner import VideoCombiner
from .dubbing_automation import DubbingAutomation

__all__ = [
    "SRTEntry",
    "SRTParser",
    "AudioGenerator",
    "VideoCombiner",
    "DubbingAutomation",
]
