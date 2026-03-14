"""テキスト前処理モジュール

英語を日本語話者が読みやすいカタカナ英語に置き換えることを目的とします。
"""

from __future__ import annotations

import csv
import re
import requests
import unicodedata
from pathlib import Path
from typing import Dict, Match, Optional
import urllib.parse


class TextPreprocessor:
    """読み方調整とカタカナ英語変換を担うクラス。"""

    # 辞書で扱う単語形式（英数字 + 内部ハイフン/アポストロフィ + 先頭アポストロフィ）を広く拾う
    WORD_PATTERN = re.compile(r"(?<![A-Za-z0-9])['’]?[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*(?![A-Za-z0-9])")

    @staticmethod
    def _resolve_default_csv(base_dir: Path, filename: str) -> Path:
        """候補パスを優先順に探索し、最初に見つかったCSVを返す。"""

        candidates = [
            base_dir.parent / filename,
            base_dir / filename,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def __init__(
        self,
        adjustments_csv: Optional[Path] = None,
        english_dict_csv: Optional[Path] = None,
    ) -> None:
        """設定ファイルを読み込んで辞書を初期化する。"""

        base_dir = Path(__file__).parent

        if adjustments_csv is None:
            adjustments_csv = self._resolve_default_csv(base_dir, "reading_adjustments.csv")
        elif isinstance(adjustments_csv, str):
            adjustments_csv = Path(adjustments_csv)

        if english_dict_csv is None:
            english_dict_csv = self._resolve_default_csv(base_dir, "english_katakana_dict.csv")
        elif isinstance(english_dict_csv, str):
            english_dict_csv = Path(english_dict_csv)

        self.reading_adjustments = self._load_adjustments(adjustments_csv)
        self.english_dict = self._load_english_dict(english_dict_csv)

    def convert_english_to_katakana(self, text: str) -> str:
        """英単語を辞書でカタカナに変換する。辞書にない単語はそのまま返す。"""

        # 全角英数や互換文字を吸収し、辞書キーと同じ正規化規則で比較できるようにする
        normalized_text = unicodedata.normalize("NFKC", text)

        def replace(match: Match[str]) -> str:
            english_word = match.group(0)
            
            # 辞書を参照。なければそのまま返す（VITS2が読み上げる）
            katakana = self._lookup_dictionary(english_word)
            if katakana:
                return katakana
            
            return english_word

        return self.WORD_PATTERN.sub(replace, normalized_text)


    @staticmethod
    def _normalize_english_key(word: str) -> str:
        """英語辞書キー比較用に、Unicode正規化 + apostrophe統一 + casefold を適用する。"""

        normalized = unicodedata.normalize("NFKC", word).strip()
        normalized = normalized.replace("’", "'")
        return normalized.casefold()

    
    def _lookup_dictionary(self, english_word: str) -> Optional[str]:
        """辞書参照時に簡単な語尾ゆれを吸収する。"""

        base = self._normalize_english_key(english_word)
        candidates = [base]

        if re.fullmatch(r"[a-z]+'s", base):
            candidates.append(base[:-2])
        if re.fullmatch(r"[a-z]+es", base):
            candidates.append(base[:-2])
        if re.fullmatch(r"[a-z]+s", base):
            candidates.append(base[:-1])
        if re.fullmatch(r"[a-z]+ed", base):
            candidates.append(base[:-2])
        if re.fullmatch(r"[a-z]+ing", base):
            candidates.append(base[:-3])

        for candidate in candidates:
            if candidate in self.english_dict:
                return self.english_dict[candidate]

        return None

    def _load_english_dict(self, csv_path: Path) -> Dict[str, str]:
        """
        CSVファイルから英単語→カタカナ辞書を読み込む
        
        CSVフォーマット: 英単語,カタカナ
        例: Hello,ハロー
        
        Args:
            csv_path: CSVファイルパス
            
        Returns:
            英単語→カタカナ辞書（キーは小文字）
        """
        english_dict: dict[str, str] = {}
        
        if not csv_path.exists():
            print(f"[INFO] 英単語辞書ファイルが見つかりません: {csv_path}")
            print("       辞書なしで動作します（英単語はそのまま）。")
            return english_dict
        
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    # コメント行をスキップ
                    if not row or row[0].startswith('#'):
                        continue
                    
                    if len(row) >= 2:
                        english = self._normalize_english_key(row[0])
                        katakana = row[1].strip()
                        if english and katakana:
                            english_dict[english] = katakana
            
            print(f"[OK] 英単語辞書を{len(english_dict)}件読み込みました: {csv_path}")
        except Exception as e:
            print(f"[WARN] 英単語辞書ファイルの読み込みエラー: {e}")
            print("        辞書なしで動作します（英単語はそのまま）。")
        
        return english_dict
    
    def _load_adjustments(self, csv_path: Path) -> Dict[str, str]:
        """
        CSVファイルから読み方調整辞書を読み込む
        
        CSVフォーマット: 元の表記,読み方
        例: 日本,にほん
        
        Args:
            csv_path: CSVファイルパス
            
        Returns:
            読み方調整辞書
        """
        adjustments: dict[str, str] = {}
        
        if not csv_path.exists():
            print(f"[INFO] 読み方調整ファイルが見つかりません: {csv_path}")
            print("       デフォルト設定で動作します。")
            return adjustments
        
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    # コメント行とヘッダーをスキップ
                    if not row or row[0].startswith('#') or row[0] == '元の表記':
                        continue
                    
                    if len(row) >= 2:
                        original = row[0].strip()
                        reading = row[1].strip()
                        if original and reading:
                            adjustments[original] = reading
            
            print(f"[OK] 読み方調整を{len(adjustments)}件読み込みました: {csv_path}")
        except Exception as e:
            print(f"[WARN] 読み方調整ファイルの読み込みエラー: {e}")
            print("        デフォルト設定で動作します。")
        
        return adjustments
    
    def preprocess(self, text: str) -> str:
        """読み方調整→英語→カタカナ英語変換の順で処理する。"""

        # 読み方の微調整（CSVから読み込んだ辞書を使用）
        for word, reading in self.reading_adjustments.items():
            text = text.replace(word, reading)

        # 例: "Brush Tip Shape" -> "ブラッシュ ティップ シェープ"
        return self.convert_english_to_katakana(text)
    
    @staticmethod
    def _katakana_to_hiragana(text: str) -> str:
        """
        カタカナをひらがなに変換
        
        Args:
            text: カタカナ文字列
            
        Returns:
            ひらがな文字列
        """
        result = []
        for char in text:
            code = ord(char)
            # カタカナ範囲（ァ-ヶ: 0x30A1-0x30F6）
            if 0x30A1 <= code <= 0x30F6:
                # ひらがなに変換（ぁ-ゖ: 0x3041-0x3096）
                result.append(chr(code - 0x60))
            else:
                result.append(char)
        return ''.join(result)


# モジュールレベルでインスタンスを保持（再利用）
_preprocessor_instance: Optional[TextPreprocessor] = None


def get_preprocessor(force_reload: bool = False) -> TextPreprocessor:
    """テキスト前処理インスタンスを取得（必要に応じて再生成）。"""

    global _preprocessor_instance
    if force_reload or _preprocessor_instance is None:
        _preprocessor_instance = TextPreprocessor()
    return _preprocessor_instance
