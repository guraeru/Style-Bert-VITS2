import re
import unicodedata

from num2words import num2words

from style_bert_vits2.nlp.symbols import PUNCTUATIONS


# 記号類の正規化マップ
__REPLACE_MAP = {
    "：": ",",
    "；": ",",
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "\n": ".",
    "．": ".",
    "…": "...",
    "···": "...",
    "・・・": "...",
    "·": ",",
    "・": ",",
    "、": ",",
    "$": ".",
    "“": "'",
    "”": "'",
    '"': "'",
    "‘": "'",
    "’": "'",
    "（": "'",
    "）": "'",
    "(": "'",
    ")": "'",
    "《": "'",
    "》": "'",
    "【": "'",
    "】": "'",
    "[": "'",
    "]": "'",
    # NFKC 正規化後のハイフン・ダッシュの変種を全て通常半角ハイフン - \u002d に変換
    "\u02d7": "\u002d",  # ˗, Modifier Letter Minus Sign
    "\u2010": "\u002d",  # ‐, Hyphen,
    # "\u2011": "\u002d",  # ‑, Non-Breaking Hyphen, NFKC により \u2010 に変換される
    "\u2012": "\u002d",  # ‒, Figure Dash
    "\u2013": "\u002d",  # –, En Dash
    "\u2014": "\u002d",  # —, Em Dash
    "\u2015": "\u002d",  # ―, Horizontal Bar
    "\u2043": "\u002d",  # ⁃, Hyphen Bullet
    "\u2212": "\u002d",  # −, Minus Sign
    "\u23af": "\u002d",  # ⎯, Horizontal Line Extension
    "\u23e4": "\u002d",  # ⏤, Straightness
    "\u2500": "\u002d",  # ─, Box Drawings Light Horizontal
    "\u2501": "\u002d",  # ━, Box Drawings Heavy Horizontal
    "\u2e3a": "\u002d",  # ⸺, Two-Em Dash
    "\u2e3b": "\u002d",  # ⸻, Three-Em Dash
    # "～": "-",  # これは長音記号「ー」として扱うよう変更
    # "~": "-",  # これも長音記号「ー」として扱うよう変更
    "「": "'",
    "」": "'",
}
# 記号類の正規化パターン
__REPLACE_PATTERN = re.compile("|".join(re.escape(p) for p in __REPLACE_MAP))
# 句読点等の正規化パターン
__PUNCTUATION_CLEANUP_PATTERN = re.compile(
    # ↓ ひらがな、カタカナ、漢字、〇(U+3007)
    r"[^\u3005-\u3007\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\u3400-\u4DBF"
    # ↓ 半角アルファベット（大文字と小文字）
    + r"\u0041-\u005A\u0061-\u007A"
    # ↓ 全角アルファベット（大文字と小文字）
    + r"\uFF21-\uFF3A\uFF41-\uFF5A"
    # ↓ ギリシャ文字
    + r"\u0370-\u03FF\u1F00-\u1FFF"
    # ↓ "!", "?", "…", ",", ".", "'", "-", 但し`…`はすでに`...`に変換されている
    + "".join(PUNCTUATIONS) + r"]+",  # fmt: skip
)
# 数字・通貨記号の正規化パターン
__CURRENCY_MAP = {"$": "ドル", "¥": "円", "£": "ポンド", "€": "ユーロ"}
__CURRENCY_PATTERN = re.compile(r"([$¥£€])([0-9.]*[0-9])")
__NUMBER_PATTERN = re.compile(r"[0-9]+(\.[0-9]+)?")
__NUMBER_WITH_SEPARATOR_PATTERN = re.compile("[0-9]{1,3}(,[0-9]{3})+")

# 日付パターン: 数字+月+数字+日 → 漢数字に変換して pyopenjtalk の読みを改善
__DATE_PATTERN = re.compile(r"(\d{1,2})月(\d{1,2})日")
# 助数詞パターン: 数字+助数詞 → 漢数字+助数詞に変換
# pyopenjtalk は漢数字+助数詞の方が正しい読みを返しやすい
__COUNTER_PATTERN = re.compile(
    r"(\d+)(人|本|匹|頭|羽|冊|枚|台|杯|階|つ|個|回|歳|才|年|月|日|時|分|秒|番|丁目)"
)

# 漢数字変換用
__NUM_TO_KANJI: dict[str, str] = {
    "0": "〇", "1": "一", "2": "二", "3": "三", "4": "四",
    "5": "五", "6": "六", "7": "七", "8": "八", "9": "九",
}


def __num_to_kanji_simple(num_str: str) -> str:
    """数字文字列を単純に漢数字に1文字ずつ変換する（読み精度向上用）。"""
    return "".join(__NUM_TO_KANJI.get(c, c) for c in num_str)


def normalize_text(text: str) -> str:
    """
    日本語のテキストを正規化する。
    結果は、ちょうど次の文字のみからなる：
    - ひらがな
    - カタカナ（全角長音記号「ー」が入る！）
    - 漢字
    - 半角アルファベット（大文字と小文字）
    - ギリシャ文字
    - `.` （句点`。`や`…`の一部や改行等）
    - `,` （読点`、`や`:`等）
    - `?` （疑問符`？`）
    - `!` （感嘆符`！`）
    - `'` （`「`や`」`等）
    - `-` （`―`（ダッシュ、長音記号ではない）や`-`等）

    注意点:
    - 三点リーダー`…`は`...`に変換される（`なるほど…。` → `なるほど....`）
    - 数字は漢字に変換される（`1,100円` → `千百円`、`52.34` → `五十二点三四`）
    - 読点や疑問符等の位置・個数等は保持される（`??あ、、！！！` → `??あ,,!!!`）

    Args:
        text (str): 正規化するテキスト

    Returns:
        str: 正規化されたテキスト
    """

    res = unicodedata.normalize("NFKC", text)  # ここでアルファベットは半角になる
    res = __convert_numbers_to_words(res)  # 「100円」→「百円」等
    # 「～」と「〜」と「~」も長音記号として扱う
    res = res.replace("~", "ー")
    res = res.replace("～", "ー")
    res = res.replace("〜", "ー")

    res = replace_punctuation(res)  # 句読点等正規化、読めない文字を削除

    # 結合文字の濁点・半濁点を削除
    # 通常の「ば」等はそのままのこされる、「あ゛」は上で「あ゙」になりここで「あ」になる
    res = res.replace("\u3099", "")  # 結合文字の濁点を削除、る゙ → る
    res = res.replace("\u309a", "")  # 結合文字の半濁点を削除、な゚ → な
    return res


def replace_punctuation(text: str) -> str:
    """
    句読点等を「.」「,」「!」「?」「'」「-」に正規化し、OpenJTalk で読みが取得できるもののみ残す：
    漢字・平仮名・カタカナ、アルファベット、ギリシャ文字

    Args:
        text (str): 正規化するテキスト

    Returns:
        str: 正規化されたテキスト
    """

    # 句読点を辞書で置換
    replaced_text = __REPLACE_PATTERN.sub(lambda x: __REPLACE_MAP[x.group()], text)

    # 上述以外の文字を削除
    replaced_text = __PUNCTUATION_CLEANUP_PATTERN.sub("", replaced_text)

    return replaced_text


def __convert_numbers_to_words(text: str) -> str:
    """
    記号や数字を日本語の文字表現に変換する。
    日付や助数詞パターンは漢数字に変換し、それ以外は num2words で読みに変換する。

    Args:
        text (str): 変換するテキスト

    Returns:
        str: 変換されたテキスト
    """

    res = __NUMBER_WITH_SEPARATOR_PATTERN.sub(lambda m: m[0].replace(",", ""), text)
    res = __CURRENCY_PATTERN.sub(lambda m: m[2] + __CURRENCY_MAP.get(m[1], m[1]), res)

    # 日付パターンを先に漢数字に変換（pyopenjtalk の読み精度向上）
    # 例: "3月14日" → "三月一四日" ではなく "3月14日" → num2words 経由
    # ※ 月日は num2words が適切に処理するのでここでは特殊処理不要

    # 助数詞パターンは漢数字に変換（pyopenjtalk が正しい読みを返しやすい）
    # 例: "3人" → "三人"（num2words だと "三" になるので結果は同じだが明示的に処理）
    # 年・月・日・時・分・秒は位取りが必要なので num2words で変換する
    # 例: "2013年" → "二千十三年"（__num_to_kanji_simple だと "二〇一三年" になり、
    #     〇が除去されて "二一三年"→"二百十三年" と誤読される）
    __NUM2WORDS_COUNTERS = {"年", "月", "日", "時", "分", "秒"}

    def _counter_to_kanji(m: re.Match[str]) -> str:
        num_part = m.group(1)
        counter = m.group(2)
        # 大きな数字または位取りが必要な助数詞は num2words に任せる
        if len(num_part) > 4 or counter in __NUM2WORDS_COUNTERS:
            return num2words(num_part, lang="ja") + counter
        return __num_to_kanji_simple(num_part) + counter

    res = __COUNTER_PATTERN.sub(_counter_to_kanji, res)

    # 残りの数字を num2words で変換
    res = __NUMBER_PATTERN.sub(lambda m: num2words(m[0], lang="ja"), res)

    return res
