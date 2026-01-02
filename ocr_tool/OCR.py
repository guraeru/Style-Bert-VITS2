# OCR.py - OCRエンジンクラス群
# Tesseract判定 + EasyOCR/Tesseract実行のハイブリッド方式

import easyocr
import torch
import numpy as np
import cv2
from PIL import Image
import pytesseract

# Tesseractのデフォルトパス
TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 正規化辞書（誤認識 → 正しい表記）
NORMALIZATION_DICT = {
    " ": "",      # 半角スペース削除
    "　": "",      # 全角スペース削除
    "\n": "",     # 改行削除
    "\r": "",     # 改行削除
    "~般的": "一般的",
    "魅カ": "魅力",
    "均-": "均一",
    "猫い": "描い",
    "猫く": "描く",
    "猫〈": "描く",
    "猫る": "描る",
    "猫け": "描け",
    "カーフ": "カーブ",
    "摘く": "描く",
    "落ち考い": "落ち着い",
    "榛足": "襟足",
    "|": "",
    "[": "",
    "]": "",
    "四ま": "凹ま",
    "四む": "凹む",
    "四ん": "凹ん",
    "中問": "中間",
    "橋円": "楕円",
    "顕頂部": "頭頂部",
    "顕部": "頭部",
    "シト日": "ジト目",
    "オ能": "才能",
}

# ==============================================================================
# 補助関数
# ==============================================================================
def _oothushiki_2tika(cv_img_bgr, threshold=None):
    """
    固定値または大津の二値化で処理する関数。
    
    Args:
        cv_img_bgr: OpenCV形式 (BGR) の入力画像。
        threshold: Noneの場合: 大津の二値化を適用し、最適な値を自動決定。
                   intの場合: その値で固定の二値化を適用。

    Returns:
        二値化された画像 (グレースケール/NumPy配列)。
    """
    # 1. グレースケール変換
    gray_img = cv2.cvtColor(cv_img_bgr, cv2.COLOR_BGR2GRAY)

    # 2. しきい値の決定と二値化の実行
    if threshold is None:
        print("    [前処理] 大津の二値化を適用 (自動決定)")
        otsu_threshold, binarized_img = cv2.threshold(
            gray_img, 
            0,
            255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
        print(f"    [大津の二値化] 自動決定された最適しきい値: {int(otsu_threshold)}")
    else:
        print(f"    [前処理] 固定しきい値 {threshold} を適用")
        _, binarized_img = cv2.threshold(
            gray_img, 
            threshold,
            255,
            cv2.THRESH_BINARY
        )
    
    return binarized_img


def _resize_image(image, scale=2.0):
    """
    画像を指定倍率で拡大・縮小する関数

    Parameters:
        image: OpenCV形式（BGR）の画像
        scale: 拡大・縮小倍率（例: 2.0 → 2倍拡大）

    Returns:
        拡大後の画像
    """
    height, width = image.shape[:2]
    new_width = int(width * scale)
    new_height = int(height * scale)

    # INTER_CUBIC は拡大時に高品質（手書き文字に有効）
    resized_image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    return resized_image


def _normalize_text(text, normalization_dict=None):
    """
    正規化辞書に基づいてOCR結果の文字列を修正する関数。

    Parameters:
        text: 元のOCR抽出テキスト
        normalization_dict: 誤認識 → 正しい表記の辞書

    Returns:
        修正後のテキスト
    """
    if normalization_dict is None:
        normalization_dict = NORMALIZATION_DICT
    for wrong, correct in normalization_dict.items():
        text = text.replace(wrong, correct)
    return text.strip()


# ==============================================================================
# Tesseract OCR クラス (信頼度スコアで文字種を判定)
# ==============================================================================
class ScreenOCRTool_Tesseract:

    def __init__(self, langs='jpn+eng', tesseract_cmd=TESSERACT_CMD):
        print("OCRツールを初期化中 (Tesseract OCR)...")
        self.langs = langs 
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError:
            raise FileNotFoundError(f"Tesseractの実行ファイルが見つかりません。パス: {tesseract_cmd} を確認してください。")
        print(f"Tesseractリーダーの準備が完了しました。使用言語: {self.langs}")
        
    def _run_tesseract_raw(self, image):
        """ Tesseract OCRを内部的に実行し、生のテキストを返すヘルパー関数。 """
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_image)
        config = '--oem 1 --psm 6'
        return pytesseract.image_to_string(pil_image, lang=self.langs, config=config)

    def detect_writing_status(self, image, confidence_threshold=70, low_confidence_ratio_limit=0.05):
        """ Tesseract OCRの単語ごとの信頼度スコアに基づいて、手書き/印刷文字を判定する。 """
        try:
            config = '--oem 1 --psm 6'
            data = pytesseract.image_to_data(image, lang=self.langs, output_type=pytesseract.Output.DICT, config=config)
            
            total_words = 0
            low_confidence_words = 0
            
            print("\n--- Tesseract 信頼度の詳細 ---")
            
            for i, conf in enumerate(data['conf']):
                text = data['text'][i]
                
                if int(conf) > 0 and text.strip() != '':
                    total_words += 1
                    conf_value = int(conf)
                    
                    print(f"[{i+1}] テキスト: '{text}', 信頼度: {conf_value}")
                    
                    if conf_value < confidence_threshold:
                        low_confidence_words += 1

            print("--------------------------")
            
            if total_words == 0:
                return True, "手書きの可能性が高いです (Tesseractが有効な文字を認識不能)"

            low_confidence_ratio = low_confidence_words / total_words
            
            print(f"Tesseract判定詳細: 総単語数={total_words}, 低信頼度単語数={low_confidence_words}, 低信頼度比率={low_confidence_ratio:.2f}")

            if low_confidence_ratio > low_confidence_ratio_limit:
                return True, f"手書きの可能性が高いです (低信頼度比率 {low_confidence_ratio:.2f} が閾値 {low_confidence_ratio_limit:.2f} を超えました)"

            return False, "印刷文字の可能性が高いです"

        except Exception as e:
            print(f"[Tesseract判定エラー]: {e}")
            return True, f"[Tesseract判定失敗: {type(e).__name__}]"

    def run_ocr(self, image):
        """ OCRを実行し、抽出テキストを返す。 """
        try:
            text = self._run_tesseract_raw(image)
            return text.strip() if text.strip() else "[テキストが検出されませんでした]"
        except Exception as e:
            return f"[OCR失敗 (Tesseract): {type(e).__name__}: {e}]"


# ==============================================================================
# EasyOCR クラス (手書き文字の抽出専用)
# ==============================================================================
class ScreenOCRTool_easyocr:
    
    def __init__(self, langs=None, use_cuda=None):
        print("OCRツールを初期化中 (EasyOCR)...")
        if langs is None:
            langs = ['ja', 'en']
        if use_cuda is None:
            self.use_cuda = torch.cuda.is_available()
        else:
            self.use_cuda = use_cuda
        # EasyOCRリーダーの初期化
        self.reader = easyocr.Reader(langs, gpu=self.use_cuda)
        print("EasyOCRリーダーの準備が完了しました。")

    def run_ocr(self, image):
        """ 手書き文字としてEasyOCRを実行し、テキストを抽出する。 """
        print("✍️ EasyOCR（手書き文字用）で抽出中...")

        try:
            # EasyOCRでは拡大・二値化などの前処理が有効
            image = _resize_image(image, scale=2.0) 
            results = self.reader.readtext(image)
            if results:
                # 抽出結果を改行で結合し、不要なスペースを削除
                text = "\n".join([text for _, text, _ in results]).replace(" ", "")
                return text.strip()
            else:
                return "[テキストが検出されませんでした]"
        except Exception as e:
            return f"[OCR失敗 (EasyOCR): {type(e).__name__}: {e}]"


# ==============================================================================
# 高精度OCRクラス (変更前の高精度モデルを流用)
# Tesseract判定 + EasyOCR/Tesseract実行のハイブリッド方式
# ==============================================================================
class HighAccuracyOCRTool:
    """
    高精度OCRツール。
    Tesseractで文字種を判定し、手書き文字の場合はEasyOCR、
    印刷文字の場合はTesseract OCRを使用する。
    変更前の高精度モデルの処理を流用。
    """
    
    def __init__(self, tesseract_langs='jpn+eng', easyocr_langs=None, 
                 use_cuda=None, tesseract_cmd=TESSERACT_CMD):
        print("高精度OCRツールを初期化中...")
        
        if easyocr_langs is None:
            easyocr_langs = ['ja', 'en']
        
        # Tesseract設定
        self.tesseract_langs = tesseract_langs
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError:
            raise FileNotFoundError(f"Tesseractの実行ファイルが見つかりません。パス: {tesseract_cmd} を確認してください。")
        print(f"Tesseractリーダーの準備が完了しました。使用言語: {self.tesseract_langs}")
        
        # EasyOCR設定
        if use_cuda is None:
            self.use_cuda = torch.cuda.is_available()
        else:
            self.use_cuda = use_cuda
        self.easyocr_reader = easyocr.Reader(easyocr_langs, gpu=self.use_cuda)
        print("EasyOCRリーダーの準備が完了しました。")
        
        print("✅ 高精度OCRツールの初期化が完了しました。")
    
    def _run_tesseract_raw(self, image):
        """ Tesseract OCRを内部的に実行し、生のテキストを返すヘルパー関数。 """
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_image)
        config = '--oem 1 --psm 6'
        return pytesseract.image_to_string(pil_image, lang=self.tesseract_langs, config=config)
    
    def detect_writing_status(self, image, confidence_threshold=70, low_confidence_ratio_limit=0.05):
        """ Tesseract OCRの単語ごとの信頼度スコアに基づいて、手書き/印刷文字を判定する。 """
        try:
            config = '--oem 1 --psm 6'
            data = pytesseract.image_to_data(image, lang=self.tesseract_langs, 
                                              output_type=pytesseract.Output.DICT, config=config)
            
            total_words = 0
            low_confidence_words = 0
            
            print("\n--- Tesseract 信頼度の詳細 ---")
            
            for i, conf in enumerate(data['conf']):
                text = data['text'][i]
                
                if int(conf) > 0 and text.strip() != '':
                    total_words += 1
                    conf_value = int(conf)
                    
                    print(f"[{i+1}] テキスト: '{text}', 信頼度: {conf_value}")
                    
                    if conf_value < confidence_threshold:
                        low_confidence_words += 1

            print("--------------------------")
            
            if total_words == 0:
                return True, "手書きの可能性が高いです (Tesseractが有効な文字を認識不能)"

            low_confidence_ratio = low_confidence_words / total_words
            
            print(f"Tesseract判定詳細: 総単語数={total_words}, 低信頼度単語数={low_confidence_words}, 低信頼度比率={low_confidence_ratio:.2f}")

            if low_confidence_ratio > low_confidence_ratio_limit:
                return True, f"手書きの可能性が高いです (低信頼度比率 {low_confidence_ratio:.2f} が閾値 {low_confidence_ratio_limit:.2f} を超えました)"

            return False, "印刷文字の可能性が高いです"

        except Exception as e:
            print(f"[Tesseract判定エラー]: {e}")
            return True, f"[Tesseract判定失敗: {type(e).__name__}]"
    
    def _run_tesseract_ocr(self, image):
        """ 印刷文字用のTesseract OCR実行。 """
        try:
            text = self._run_tesseract_raw(image)
            return text.strip() if text.strip() else "[テキストが検出されませんでした]"
        except Exception as e:
            return f"[OCR失敗 (Tesseract): {type(e).__name__}: {e}]"
    
    def _run_easyocr(self, image):
        """ 手書き文字用のEasyOCR実行。 """
        print("✍️ EasyOCR（手書き文字用）で抽出中...")
        try:
            # EasyOCRでは拡大などの前処理が有効
            processed_image = _resize_image(image, scale=2.0)
            results = self.easyocr_reader.readtext(processed_image)
            if results:
                # 抽出結果を改行で結合し、不要なスペースを削除
                text = "\n".join([text for _, text, _ in results]).replace(" ", "")
                return text.strip()
            else:
                return "[テキストが検出されませんでした]"
        except Exception as e:
            return f"[OCR失敗 (EasyOCR): {type(e).__name__}: {e}]"
    
    def run_ocr(self, image):
        """
        高精度OCRを実行するメインメソッド。
        1. Tesseractで文字種を判定
        2. 判定結果に基づきOCRエンジンを切り替え
        3. 結果を正規化して返す
        """
        # 1. Tesseractで文字種判定
        print("\n🔎 Tesseractによる文字種判定を実行中...")
        is_handwriting, status_message = self.detect_writing_status(image)
        print(f"最終判定結果: {status_message}")
        
        # 2. 判定結果に基づきOCRエンジンを切り替え
        if is_handwriting:
            print("✍️ 手書き文字と判定されました。EasyOCRで詳細抽出します。")
            final_text = self._run_easyocr(image)
        else:
            print("🖨️ 印刷文字と判定されました。Tesseract OCRで詳細抽出します。")
            final_text = self._run_tesseract_ocr(image)
        
        # 3. 正規化して返す
        return _normalize_text(final_text)
