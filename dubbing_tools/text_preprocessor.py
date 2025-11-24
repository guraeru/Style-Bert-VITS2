"""テキスト前処理モジュール

TTSモデルの読み精度を向上させるため、英語をカタカナに変換します。
"""

import re
import csv
from pathlib import Path
from typing import Dict, Optional


class TextPreprocessor:
    """
    テキスト前処理クラス
    
    英語をカタカナに変換してTTS精度を向上させます。
    """
    
    # ローマ字→カタカナマッピング辞書（網羅版）
    ROMAJI_MAP = {
        # 4文字の組み合わせ
        'ksha': 'クシャ', 'kshu': 'クシュ', 'ksho': 'クショ',
        'tsya': 'チャ', 'tsyu': 'チュ', 'tsyo': 'チョ',
        
        # 3文字の組み合わせ
        'kya': 'キャ', 'kyi': 'キィ', 'kyu': 'キュ', 'kye': 'キェ', 'kyo': 'キョ',
        'kwa': 'クァ', 'kwi': 'クィ', 'kwu': 'クゥ', 'kwe': 'クェ', 'kwo': 'クォ',
        'gya': 'ギャ', 'gyi': 'ギィ', 'gyu': 'ギュ', 'gye': 'ギェ', 'gyo': 'ギョ',
        'gwa': 'グァ', 'gwi': 'グィ', 'gwu': 'グゥ', 'gwe': 'グェ', 'gwo': 'グォ',
        'sha': 'シャ', 'shi': 'シ', 'shu': 'シュ', 'she': 'シェ', 'sho': 'ショ',
        'sya': 'シャ', 'syi': 'シィ', 'syu': 'シュ', 'sye': 'シェ', 'syo': 'ショ',
        'swa': 'スァ', 'swi': 'スィ', 'swu': 'スゥ', 'swe': 'スェ', 'swo': 'スォ',
        'zya': 'ジャ', 'zyi': 'ジィ', 'zyu': 'ジュ', 'zye': 'ジェ', 'zyo': 'ジョ',
        'cha': 'チャ', 'chi': 'チ', 'chu': 'チュ', 'che': 'チェ', 'cho': 'チョ',
        'tya': 'チャ', 'tyi': 'チィ', 'tyu': 'チュ', 'tye': 'チェ', 'tyo': 'チョ',
        'tsa': 'ツァ', 'tsi': 'ツィ', 'tsu': 'ツ', 'tse': 'ツェ', 'tso': 'ツォ',
        'tha': 'テァ', 'thi': 'ティ', 'thu': 'テゥ', 'the': 'テェ', 'tho': 'テォ',
        'twa': 'トァ', 'twi': 'トィ', 'twu': 'トゥ', 'twe': 'トェ', 'two': 'トォ',
        'dya': 'ヂャ', 'dyi': 'ヂィ', 'dyu': 'ヂュ', 'dye': 'ヂェ', 'dyo': 'ヂョ',
        'dha': 'デァ', 'dhi': 'ディ', 'dhu': 'デゥ', 'dhe': 'デェ', 'dho': 'デォ',
        'dwa': 'ドァ', 'dwi': 'ドィ', 'dwu': 'ドゥ', 'dwe': 'ドェ', 'dwo': 'ドォ',
        'nya': 'ニャ', 'nyi': 'ニィ', 'nyu': 'ニュ', 'nye': 'ニェ', 'nyo': 'ニョ',
        'hya': 'ヒャ', 'hyi': 'ヒィ', 'hyu': 'ヒュ', 'hye': 'ヒェ', 'hyo': 'ヒョ',
        'bya': 'ビャ', 'byi': 'ビィ', 'byu': 'ビュ', 'bye': 'ビェ', 'byo': 'ビョ',
        'pya': 'ピャ', 'pyi': 'ピィ', 'pyu': 'ピュ', 'pye': 'ピェ', 'pyo': 'ピョ',
        'fya': 'フャ', 'fyi': 'フィ', 'fyu': 'フュ', 'fye': 'フェ', 'fyo': 'フョ',
        'mya': 'ミャ', 'myi': 'ミィ', 'myu': 'ミュ', 'mye': 'ミェ', 'myo': 'ミョ',
        'rya': 'リャ', 'ryi': 'リィ', 'ryu': 'リュ', 'rye': 'リェ', 'ryo': 'リョ',
        'lya': 'リャ', 'lyi': 'リィ', 'lyu': 'リュ', 'lye': 'リェ', 'lyo': 'リョ',
        'vya': 'ヴャ', 'vyi': 'ヴィ', 'vyu': 'ヴュ', 'vye': 'ヴェ', 'vyo': 'ヴョ',
        
        # 2文字の組み合わせ（基本）
        'ka': 'カ', 'ki': 'キ', 'ku': 'ク', 'ke': 'ケ', 'ko': 'コ',
        'ga': 'ガ', 'gi': 'ギ', 'gu': 'グ', 'ge': 'ゲ', 'go': 'ゴ',
        'sa': 'サ', 'si': 'シ', 'su': 'ス', 'se': 'セ', 'so': 'ソ',
        'za': 'ザ', 'zi': 'ジ', 'zu': 'ズ', 'ze': 'ゼ', 'zo': 'ゾ',
        'ta': 'タ', 'ti': 'チ', 'tu': 'ツ', 'te': 'テ', 'to': 'ト',
        'da': 'ダ', 'di': 'ヂ', 'du': 'ヅ', 'de': 'デ', 'do': 'ド',
        'na': 'ナ', 'ni': 'ニ', 'nu': 'ヌ', 'ne': 'ネ', 'no': 'ノ',
        'ha': 'ハ', 'hi': 'ヒ', 'hu': 'フ', 'fu': 'フ', 'he': 'ヘ', 'ho': 'ホ',
        'ba': 'バ', 'bi': 'ビ', 'bu': 'ブ', 'be': 'ベ', 'bo': 'ボ',
        'pa': 'パ', 'pi': 'ピ', 'pu': 'プ', 'pe': 'ペ', 'po': 'ポ',
        'ma': 'マ', 'mi': 'ミ', 'mu': 'ム', 'me': 'メ', 'mo': 'モ',
        'ya': 'ヤ', 'yi': 'イ', 'yu': 'ユ', 'ye': 'イェ', 'yo': 'ヨ',
        'ra': 'ラ', 'ri': 'リ', 'ru': 'ル', 're': 'レ', 'ro': 'ロ',
        'wa': 'ワ', 'wi': 'ウィ', 'wu': 'ウ', 'we': 'ウェ', 'wo': 'ヲ',
        'nn': 'ン',
        
        # 英語用の追加マッピング（C, L, V, F, J, Q, X など）
        'ca': 'カ', 'ci': 'シ', 'cu': 'ク', 'ce': 'セ', 'co': 'コ',
        'la': 'ラ', 'li': 'リ', 'lu': 'ル', 'le': 'レ', 'lo': 'ロ',
        'va': 'ヴァ', 'vi': 'ヴィ', 'vu': 'ヴ', 've': 'ヴェ', 'vo': 'ヴォ',
        'fa': 'ファ', 'fi': 'フィ', 'fu': 'フ', 'fe': 'フェ', 'fo': 'フォ',
        'ja': 'ジャ', 'ji': 'ジ', 'ju': 'ジュ', 'je': 'ジェ', 'jo': 'ジョ',
        'qa': 'クァ', 'qi': 'クィ', 'qu': 'クゥ', 'qe': 'クェ', 'qo': 'クォ',
        'xa': 'クサ', 'xi': 'クシ', 'xu': 'クス', 'xe': 'クセ', 'xo': 'クソ',
        
        # ウ段拗音
        'wha': 'ウァ', 'whi': 'ウィ', 'whu': 'ウ', 'whe': 'ウェ', 'who': 'ウォ',
        
        # 小さいカナ
        'xya': 'ャ', 'xyu': 'ュ', 'xyo': 'ョ',
        'xwa': 'ヮ', 'xka': 'ヵ', 'xke': 'ヶ',
        'xtu': 'ッ', 'xtsu': 'ッ',
        'xa': 'ァ', 'xi': 'ィ', 'xu': 'ゥ', 'xe': 'ェ', 'xo': 'ォ',
        
        # 特殊な組み合わせ（英語の th, ph など）
        'tha': 'サ', 'thi': 'シ', 'thu': 'ス', 'the': 'ゼ', 'tho': 'ソ',
        'pha': 'ファ', 'phi': 'フィ', 'phu': 'フ', 'phe': 'フェ', 'pho': 'フォ',
        
        # 1文字（母音と撥音）
        'a': 'ア', 'i': 'イ', 'u': 'ウ', 'e': 'エ', 'o': 'オ',
        'n': 'ン',
    }
    
    def __init__(self, adjustments_csv: Optional[Path] = None):
        """
        初期化
        
        Args:
            adjustments_csv: 読み方調整CSVファイルパス(Noneならデフォルトのreading_adjustments.csvを使用)
        """
        if adjustments_csv is None:
            # デフォルト: このファイルと同じディレクトリのreading_adjustments.csv
            adjustments_csv = Path(__file__).parent / "reading_adjustments.csv"
        elif isinstance(adjustments_csv, str):
            adjustments_csv = Path(adjustments_csv)
        
        self.reading_adjustments = self._load_adjustments(adjustments_csv)
        pass
    
    def convert_english_to_katakana(self, text: str) -> str:
        """
        英語をカタカナに変換（カスタムローマ字マッピング）
        
        Args:
            text: 変換するテキスト
            
        Returns:
            英語がカタカナに変換されたテキスト
        """
        # 英単語を検出（連続するアルファベット）
        def replace_english(match):
            english_word = match.group(0)
            try:
                # ローマ字→カタカナ変換
                katakana = self._romaji_to_katakana(english_word)
                return katakana
            except Exception as e:
                print(f"カタカナ変換エラー ({english_word}): {e}")
                return english_word
        
        # 英単語パターン（大文字小文字含む）
        pattern = r'[a-zA-Z]+'
        result = re.sub(pattern, replace_english, text)
        
        return result
    
    def _romaji_to_katakana(self, text: str) -> str:
        """
        ローマ字をカタカナに変換（内部メソッド）
        
        英語の単語を日本語的な発音に近いカタカナに変換します。
        例: "Coloso" → "コロソ", "Hello" → "ハロー"
        
        Args:
            text: ローマ字テキスト
            
        Returns:
            カタカナテキスト
        """
        text_lower = text.lower()
        result = []
        i = 0
        
        # 母音の定義
        vowels = set('aeiou')
        
        # 特殊な子音マッピング（単独または特定の条件下で使用）
        consonant_alone = {
            'b': 'ブ', 'c': 'ク', 'd': 'ド', 'f': 'フ', 'g': 'グ',
            'h': 'フ', 'j': 'ジュ', 'k': 'ク', 'l': 'ル', 'm': 'ム',
            'n': 'ン', 'p': 'プ', 'q': 'ク', 'r': 'ル', 's': 'ス',
            't': 'ト', 'v': 'ヴ', 'w': 'ウ', 'x': 'クス', 'y': 'イ', 'z': 'ズ',
        }
        
        while i < len(text_lower):
            # 4文字マッチを試す
            if i + 4 <= len(text_lower):
                substr4 = text_lower[i:i+4]
                if substr4 in self.ROMAJI_MAP:
                    result.append(self.ROMAJI_MAP[substr4])
                    i += 4
                    continue
            
            # 3文字マッチを試す
            if i + 3 <= len(text_lower):
                substr3 = text_lower[i:i+3]
                if substr3 in self.ROMAJI_MAP:
                    result.append(self.ROMAJI_MAP[substr3])
                    i += 3
                    continue
            
            # 2文字マッチを試す
            if i + 2 <= len(text_lower):
                substr2 = text_lower[i:i+2]
                if substr2 in self.ROMAJI_MAP:
                    result.append(self.ROMAJI_MAP[substr2])
                    i += 2
                    continue
            
            # 1文字マッチを試す
            char = text_lower[i]
            if char in self.ROMAJI_MAP:
                # 母音の場合
                result.append(self.ROMAJI_MAP[char])
                i += 1
            elif char in consonant_alone:
                # 子音の場合、次の文字を確認
                if i + 1 < len(text_lower):
                    next_char = text_lower[i+1]
                    
                    # 次が母音なら子音+母音を作る
                    if next_char in vowels:
                        # 子音+母音の組み合わせを作成
                        combo = char + next_char
                        
                        # 特殊ケース: c + e/i -> se/si (英語の発音に近づける)
                        if char == 'c' and next_char in 'ei':
                            combo = 's' + next_char
                        # 特殊ケース: l -> r (日本語では区別しない)
                        elif char == 'l':
                            combo = 'r' + next_char
                        
                        # 組み合わせがマッピングにあるか確認
                        if combo in self.ROMAJI_MAP:
                            result.append(self.ROMAJI_MAP[combo])
                            i += 2
                            continue
                    
                    # 次も子音なら、促音（ッ）を挿入してから次の処理
                    if next_char in consonant_alone and next_char not in vowels:
                        result.append('ッ')
                        i += 1
                        continue
                
                # 単独子音または末尾の子音
                result.append(consonant_alone[char])
                i += 1
            else:
                # その他の文字（記号など）は元の文字を保持
                result.append(text[i])
                i += 1
        
        return ''.join(result)
    
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
            print(f"ℹ️ 読み方調整ファイルが見つかりません: {csv_path}")
            print("   デフォルト設定で動作します。")
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
            
            print(f"✅ 読み方調整を{len(adjustments)}件読み込みました: {csv_path}")
        except Exception as e:
            print(f"⚠️ 読み方調整ファイルの読み込みエラー: {e}")
            print("   デフォルト設定で動作します。")
        
        return adjustments
    
    def preprocess(self, text: str) -> str:
        """
        テキストを前処理
        
        読み方の微調整 + 英語→カタカナ変換を実行
        
        Args:
            text: 変換するテキスト
            
        Returns:
            前処理済みテキスト
        """
        # 読み方の微調整（CSVから読み込んだ辞書を使用）
        for word, reading in self.reading_adjustments.items():
            text = text.replace(word, reading)
        
        # 英語→カタカナ（常に実行）
        text = self.convert_english_to_katakana(text)
        
        return text
    
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
_preprocessor_instance = None


def get_preprocessor() -> TextPreprocessor:
    """
    テキスト前処理インスタンスを取得（シングルトン）
    
    Returns:
        TextPreprocessorインスタンス
    """
    global _preprocessor_instance
    if _preprocessor_instance is None:
        _preprocessor_instance = TextPreprocessor()
    return _preprocessor_instance
