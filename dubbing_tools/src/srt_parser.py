"""
SRTファイル解析モジュール

SRTファイルから字幕情報を抽出します。
"""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class SRTEntry:
    """SRT字幕エントリ"""
    index: int
    start_time: float  # 秒単位
    end_time: float    # 秒単位
    text: str
    
    @property
    def duration(self) -> float:
        """字幕の表示時間(秒)"""
        return self.end_time - self.start_time


class SRTParser:
    """SRTファイルパーサー"""
    
    # SRTエントリのパターン: 番号、タイムスタンプ、テキスト
    SRT_PATTERN = re.compile(
        r'(\d+)\s*\n'  # 字幕番号
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n'  # タイムスタンプ
        r'((?:.*\n)*?)'  # テキスト(複数行可)
        r'(?=\n\d+\s*\n|\Z)',  # 次のエントリまたはファイル末尾
        re.MULTILINE
    )
    
    @staticmethod
    def parse_time(time_str: str) -> float:
        """
        SRTタイムスタンプを秒数に変換
        
        Args:
            time_str: HH:MM:SS,mmm形式の文字列
            
        Returns:
            秒数(float)
            
        Example:
            >>> SRTParser.parse_time("00:01:23,456")
            83.456
        """
        # HH:MM:SS,mmm形式をパース
        time_part, ms_part = time_str.split(',')
        hours, minutes, seconds = map(int, time_part.split(':'))
        milliseconds = int(ms_part)
        
        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
        return total_seconds
    
    @classmethod
    def parse_srt(cls, srt_path: str) -> List[SRTEntry]:
        """
        SRTファイルを解析してエントリリストを返す
        
        Args:
            srt_path: SRTファイルのパス
            
        Returns:
            SRTEntryのリスト
            
        Raises:
            FileNotFoundError: ファイルが見つからない場合
            ValueError: SRT形式が不正な場合
        """
        # ファイル読み込み（エンコーディング自動検出）
        encodings = ['utf-8-sig', 'utf-8', 'shift_jis', 'cp932']
        content = None
        used_encoding = None
        
        for encoding in encodings:
            try:
                with open(srt_path, 'r', encoding=encoding) as f:
                    content = f.read()
                used_encoding = encoding
                break
            except (UnicodeDecodeError, LookupError):
                continue
        
        if content is None:
            raise ValueError(f"SRTファイルのエンコーディングを検出できませんでした: {srt_path}")
        
        print(f"SRTファイルのエンコーディング: {used_encoding}")
        
        # 正規表現でマッチング
        matches = cls.SRT_PATTERN.findall(content)
        
        if not matches:
            raise ValueError(f"有効なSRTエントリが見つかりません: {srt_path}")
        
        # SRTEntryオブジェクトに変換
        entries = []
        for match in matches:
            index_str, start_str, end_str, text = match
            
            entry = SRTEntry(
                index=int(index_str),
                start_time=cls.parse_time(start_str),
                end_time=cls.parse_time(end_str),
                text=text.rstrip('\n')  # 末尾の改行のみ削除、内部の空行は保持
            )
            entries.append(entry)
        
        return entries
