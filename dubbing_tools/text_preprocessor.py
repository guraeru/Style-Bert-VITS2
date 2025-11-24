"""テキスト前処理モジュール

英語を日本語話者が読みやすいカタカナ英語に置き換えることを目的とします。
"""

from __future__ import annotations

import csv
import re
import requests
from pathlib import Path
from typing import Dict, Match, Optional
import urllib.parse


class TextPreprocessor:
    """読み方調整とカタカナ英語変換を担うクラス。"""

    WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

    def __init__(
        self,
        adjustments_csv: Optional[Path] = None,
        english_dict_csv: Optional[Path] = None,
    ) -> None:
        """設定ファイルを読み込んで辞書を初期化する。"""

        if adjustments_csv is None:
            adjustments_csv = Path(__file__).parent / "reading_adjustments.csv"
        elif isinstance(adjustments_csv, str):
            adjustments_csv = Path(adjustments_csv)

        if english_dict_csv is None:
            english_dict_csv = Path(__file__).parent / "english_katakana_dict.csv"
        elif isinstance(english_dict_csv, str):
            english_dict_csv = Path(english_dict_csv)

        self.reading_adjustments = self._load_adjustments(adjustments_csv)
        self.english_dict = self._load_english_dict(english_dict_csv)
        self.english_dict_csv = english_dict_csv
        self._api_cache: Dict[str, Optional[str]] = {}  # API結果のキャッシュ

    def convert_english_to_katakana(self, text: str) -> str:
        """英単語を辞書→Web APIの順でカタカナ英語に変換する。"""

        def replace(match: Match[str]) -> str:
            english_word = match.group(0)
            
            # 1. 既存の辞書を参照
            katakana = self._lookup_dictionary(english_word)
            if katakana:
                return katakana

            # 2. Web APIで取得して辞書に登録
            katakana = self._fetch_and_register(english_word)
            if katakana:
                return katakana

            # 3. 変換できない場合はそのまま返す
            return english_word

        return self.WORD_PATTERN.sub(replace, text)

    def _fetch_and_register(self, english_word: str) -> Optional[str]:
        """LLMまたはWeb APIで英単語のカタカナ表記を取得し、辞書に登録する。"""
        
        base_word = english_word.lower()
        
        # 既にAPI呼び出し済みの場合はキャッシュから返す
        if base_word in self._api_cache:
            return self._api_cache[base_word]
        
        # Web APIで取得
        try:
            url = f"https://www.sljfaq.org/cgi/e2k.cgi?o=json&word={urllib.parse.quote(base_word)}&lang=ja"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                # 単語単位でカタカナを取得
                if "words" in data and len(data["words"]) > 0:
                    word_data = data["words"][0]
                    katakana = word_data.get("j_pron_spell", "")
                    
                    if katakana:
                        # 辞書に追加
                        self.english_dict[base_word] = katakana
                        self._api_cache[base_word] = katakana
                        
                        # CSVファイルに追記
                        self._append_to_csv(base_word, katakana)
                        
                        print(f"[Web API] {english_word} → {katakana} (辞書に登録)")
                        return katakana
            
        except Exception as e:
            print(f"[INFO] Web API失敗 ({english_word}): {e}")
        
        # 失敗時はキャッシュに記録
        self._api_cache[base_word] = None
        return None
    
    def _append_to_csv(self, english: str, katakana: str) -> None:
        """辞書CSVファイルに新しいエントリを追記する。"""
        
        try:
            with open(self.english_dict_csv, 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([english, katakana])
        except Exception as e:
            print(f"[WARN] CSV追記エラー: {e}")
    
    def _lookup_dictionary(self, english_word: str) -> Optional[str]:
        """辞書参照時に簡単な語尾ゆれを吸収する。"""

        base = english_word.lower()
        candidates = [base]

        if base.endswith("'s"):
            candidates.append(base[:-2])
        if base.endswith("es"):
            candidates.append(base[:-2])
        if base.endswith("s"):
            candidates.append(base[:-1])
        if base.endswith("ed"):
            candidates.append(base[:-2])
        if base.endswith("ing"):
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
        english_dict = {}
        
        if not csv_path.exists():
            print(f"[INFO] 英単語辞書ファイルが見つかりません: {csv_path}")
            print("       Web API変換のみで動作します。")
            return english_dict
        
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    # コメント行をスキップ
                    if not row or row[0].startswith('#'):
                        continue
                    
                    if len(row) >= 2:
                        english = row[0].strip().lower()  # 小文字で保存
                        katakana = row[1].strip()
                        if english and katakana:
                            english_dict[english] = katakana
            
            print(f"[OK] 英単語辞書を{len(english_dict)}件読み込みました: {csv_path}")
        except Exception as e:
            print(f"[WARN] 英単語辞書ファイルの読み込みエラー: {e}")
            print("        Web API変換のみで動作します。")
        
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
        adjustments = {}
        
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
