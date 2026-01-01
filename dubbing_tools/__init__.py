"""
dubbing_tools パッケージ

Style-Bert-VITS2 を使用した動画吹き替え自動化ツール

使用方法:
    run_batch.bat を実行
"""

from .src.dubbing_automation import DubbingAutomation

__version__ = "1.0.0"
__all__ = ['DubbingAutomation']
