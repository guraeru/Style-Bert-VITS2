# ハイブリッドOCR版 (Tesseract判定 + EasyOCR/Tesseract実行)
# Style-Bert-VITS2プロジェクト用OCR読み上げツール
import easyocr
import torch
import numpy as np
import cv2
from PIL import ImageGrab, Image 
import tkinter as tk
import pytesseract
import time
from pynput import keyboard 
from ctypes import windll
import sys
import os
from pathlib import Path
import configparser

# === パス解決: settings.ini の project_root からプロジェクトルートを取得 ===
_ocr_dir = Path(__file__).parent
_settings_cfg = configparser.ConfigParser()
_settings_cfg.read(_ocr_dir / "settings.ini", encoding="utf-8")
_project_root = _settings_cfg.get("General", "project_root", fallback="")
if not _project_root:
    _project_root = str(_ocr_dir.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Style-Bert-VITS2のTTSを使用
from style_bert_vits2.tts_model import TTSModel

# 英語→カタカナ変換用のテキストプリプロセッサをインポート（ローカルコピー優先）
try:
    from text_preprocessor import TextPreprocessor
    text_preprocessor = TextPreprocessor()
    print("✅ テキストプリプロセッサを初期化しました（英語→カタカナ変換有効）")
except Exception:
    try:
        from dubbing_tools.text_preprocessor import TextPreprocessor
        text_preprocessor = TextPreprocessor()
        print("✅ テキストプリプロセッサを初期化しました（英語→カタカナ変換有効）")
    except Exception as e:
        print(f"⚠️ テキストプリプロセッサの初期化に失敗しました: {e}")
        text_preprocessor = None

scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100.0

def load_settings():
    """settings.iniから設定を読み込む"""
    config = configparser.ConfigParser()
    settings_path = _ocr_dir / "settings.ini"
    
    # デフォルト設定
    default_settings = {
        'TTS': {'model_name': 'ui_speaker'}
    }
    
    if settings_path.exists():
        config.read(settings_path, encoding='utf-8')
        print(f"✅ 設定ファイルを読み込みました: {settings_path}")
    else:
        print(f"⚠️ 設定ファイルが見つかりません。デフォルト設定を使用します。")
        # デフォルト設定でiniファイルを作成
        for section, options in default_settings.items():
            config[section] = options
        with open(settings_path, 'w', encoding='utf-8') as f:
            config.write(f)
        print(f"📝 デフォルト設定ファイルを作成しました: {settings_path}")
    
    return config

# 設定を読み込み
settings = load_settings()

# 設定から値を取得
MODEL_NAME = settings.get('TTS', 'model_name', fallback='ui_speaker')

# Tesseractのパスはシステム環境変数に設定することを推奨しますが、今回はコード内の定義を維持します
TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# ホットキーを Shift+F9 に変更するためのキー設定
# F9が押されたときに処理をトリガーします
KEY_TO_TRIGGER = keyboard.Key.f9 

# グローバル変数としてOCRツールとキャプチャツールを宣言（初期化はメインブロックで行う）
capture_tool = None
easy_ocr_tool = None
tesseract_ocr_tool = None
tts_model = None
is_running = False # 処理の多重起動を防ぐためのフラグ

# 現在押されているキーを追跡するためのグローバルセット
current_keys = set() 

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
def _oothushiki_2tika(cv_img_bgr: np.ndarray, threshold: int | None = None) -> np.ndarray:
    """
    固定値または大津の二値化で処理する関数。
    
    Args:
        cv_img_bgr (np.ndarray): OpenCV形式 (BGR) の入力画像。
        threshold (int | None): 
            Noneの場合: 大津の二値化を適用し、最適な値を自動決定。
            intの場合: その値で固定の二値化を適用。

    Returns:
        np.ndarray: 2倍に拡大され、二値化された画像 (グレースケール/NumPy配列)。
    """
    
    # 1. グレースケール変換
    gray_img = cv2.cvtColor(cv_img_bgr, cv2.COLOR_BGR2GRAY)

    # 2. しきい値の決定と二値化の実行
    if threshold is None:
        # thresholdがNoneの場合、大津の二値化を適用 (固定しきい値は0で無視される)
        print("    [前処理] 大津の二値化を適用 (自動決定)")
        otsu_threshold, binarized_img = cv2.threshold(
            gray_img, 
            0,                     # しきい値（OTSUフラグで無視される）
            255,                   # 最大値
            cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
        print(f"    [大津の二値化] 自動決定された最適しきい値: {int(otsu_threshold)}")
    else:
        # thresholdが指定された場合、その固定値で二値化
        print(f"    [前処理] 固定しきい値 {threshold} を適用")
        # 戻り値の最初の要素は入力されたしきい値がそのまま返る
        _, binarized_img = cv2.threshold(
            gray_img, 
            threshold,             # 指定されたしきい値を適用
            255,                   # 最大値
            cv2.THRESH_BINARY
        )
    
    # 4. NumPy配列を返す
    return binarized_img

def _resize_image(image, scale=2.0):
    """
    画像を指定倍率で拡大・縮小する関数

    Parameters:
        image (np.ndarray): OpenCV形式（BGR）の画像
        scale (float): 拡大・縮小倍率（例: 2.0 → 2倍拡大）

    Returns:
        拡大後の画像（np.ndarray）
    """
    height, width = image.shape[:2]
    new_width = int(width * scale)
    new_height = int(height * scale)

    # INTER_CUBIC は拡大時に高品質（手書き文字に有効）
    resized_image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    return resized_image

def _normalize_text(text: str, normalization_dict: dict = NORMALIZATION_DICT) -> str:
    """
    正規化辞書に基づいてOCR結果の文字列を修正する関数。

    Parameters:
        text (str): 元のOCR抽出テキスト
        normalization_dict (dict): 誤認識 → 正しい表記の辞書

    Returns:
        str: 修正後のテキスト
    """
    for wrong, correct in normalization_dict.items():
        text = text.replace(wrong, correct)
    return text.strip()

# ==============================================================================
# ユーティリティ関数
# ==============================================================================

def speak_with_style_bert_vits2(text_to_speak: str):
    """ Style-Bert-VITS2を使用してテキストを読み上げます。 """
    global tts_model
    
    if tts_model is None:
        print("⚠️ TTSモデルが初期化されていません。")
        return
    
    try:
        print(f"🔊 読み上げ中: {text_to_speak}")
        # 音声生成
        sr, audio = tts_model.infer(text=text_to_speak)
        
        # 一時ファイルに保存して再生
        import tempfile
        import soundfile as sf
        import pygame
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            # soundfileを使って保存（numpyとの互換性問題を回避）
            sf.write(tmp_path, audio, sr)
        
        # pygame で再生
        pygame.mixer.init()
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        
        pygame.mixer.quit()
        os.unlink(tmp_path)
        
    except Exception as e:
        print(f"⚠️ TTS再生エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

# ==============================================================================
# 画面選択とキャプチャ用クラス
# ==============================================================================
class ScreenCaptureTool:
    def select_screen_area(self):
        """ DPI対策と *2 座標修正を組み込んだ、スクリーン座標取得プロセス。 """
        root = tk.Tk()
        try:
            # DPIスケールをリセット
            root.tk.call('tk', 'scaling', 1.0) 
        except Exception:
             pass 
             
        root.lift()
        root.attributes('-topmost', True) 
        root.attributes('-topmost', False) 
        root.attributes('-topmost', True) 

        root.attributes('-alpha', 0.3)
        root.attributes('-fullscreen', True)
        root.title("ドラッグして領域を選択 (Escでキャンセル)")
        
        canvas = tk.Canvas(root, cursor="cross", bg='gray')
        canvas.pack(fill=tk.BOTH, expand=True)

        start_x = start_y = end_x = end_y = 0
        rect = None
        
        def on_mouse_down(event):
            nonlocal start_x, start_y
            start_x, start_y = event.x, event.y

        def on_mouse_drag(event):
            nonlocal rect
            canvas.delete(rect)
            rect = canvas.create_rectangle(start_x, start_y, event.x, event.y, outline='red', width=2)

        def on_mouse_up(event):
            nonlocal end_x, end_y
            end_x, end_y = event.x, event.y
            root.quit()
        
        def on_escape(event):
            nonlocal end_x, end_y
            end_x, end_y = start_x, start_y 
            root.quit()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)
        root.bind('<Escape>', on_escape) 

        root.mainloop()
        root.destroy()

        # WindowsのDPIスケーリング対策として座標を適用
        x1, y1 = min(start_x, end_x) * scale_factor, min(start_y, end_y) * scale_factor
        x2, y2 = max(start_x, end_x) * scale_factor, max(start_y, end_y) * scale_factor
        
        return (x1, y1, x2, y2)

    def capture_screen_area(self, coords):
        """ 指定された画面領域をキャプチャし、OpenCV形式（BGR）の画像として返す。 """
        img = ImageGrab.grab(bbox=coords)
        img_np = np.array(img)
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        return img_cv

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
        # Tesseractを実行。
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
            #tesseractの場合は、二値化やリサイズなどの前処理はしない方が精度が良い、場合が多い
            #image = preprocess_image_for_ocr_combined(image)
            text = self._run_tesseract_raw(image)
            return text.strip() if text.strip() else "[テキストが検出されませんでした]"
                
        except Exception as e:
            return f"[OCR失敗 (Tesseract): {type(e).__name__}: {e}]"

# ==============================================================================
# EasyOCR クラス (手書き文字の抽出専用)
# ==============================================================================
class ScreenOCRTool_easyocr:
    
    def __init__(self, langs=['ja', 'en'], use_cuda=None):
        print("OCRツールを初期化中 (EasyOCR)...")
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
                
                # 日本語の誤認識修正を追加（_normalize_textで後処理される）
                
                return text.strip()
            else:
                return "[テキストが検出されませんでした]"
        except Exception as e:
            return f"[OCR失敗 (EasyOCR): {type(e).__name__}: {e}]"

# ==============================================================================
# ツール初期化関数
# ==============================================================================
def initialize_tools():
    """ 必要なOCRツールとキャプチャツール、TTSモデルを初期化し、グローバル変数に設定します。 """
    global capture_tool, easy_ocr_tool, tesseract_ocr_tool, tts_model

    print("--- ツール初期化 ---")
    try:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        # 初期化
        easy_ocr_tool = ScreenOCRTool_easyocr(langs=['ja','en'])
        tesseract_ocr_tool = ScreenOCRTool_Tesseract(langs='jpn+en')
        capture_tool = ScreenCaptureTool()
        
        # TTSモデル初期化
        print(f"\nTTSモデルを初期化中: {MODEL_NAME}")
        model_assets_dir = Path(_project_root) / "model_assets" / MODEL_NAME
        
        # モデルファイルを自動検索
        config_path = None
        model_path = None
        style_vec_path = None
        
        if model_assets_dir.exists():
            for file in model_assets_dir.iterdir():
                if file.suffix == '.json' and 'config' in file.name.lower():
                    config_path = file
                elif file.suffix == '.safetensors':
                    model_path = file
                elif file.suffix == '.npy' and 'style' in file.name.lower():
                    style_vec_path = file
        
        if not model_path or not config_path or not style_vec_path:
            raise FileNotFoundError(f"モデルファイルが見つかりません: {model_assets_dir}")
        
        print(f"  モデルファイル: {model_path}")
        print(f"  設定ファイル: {config_path}")
        print(f"  スタイルベクトル: {style_vec_path}")
        
        # デバイスの決定（cudaが使えない場合はcpuにフォールバック）
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            print(f"⚠️ CUDAが利用できません。CPUモードで動作します。")
        
        tts_model = TTSModel(
            model_path=model_path,
            config_path=config_path,
            style_vec_path=style_vec_path,
            device=device
        )
        
        print("✅ 全てのツールが正常に初期化されました。")
        return True # 成功
    except FileNotFoundError as e:
        print(f"❌ 致命的なエラー: Tesseractの実行ファイルが見つかりません。パス: {TESSERACT_CMD} を確認してください。")
        capture_tool = easy_ocr_tool = tesseract_ocr_tool = tts_model = None
        return False # 失敗
    except Exception as e:
        print(f"❌ 初期化エラー: {e}")
        capture_tool = easy_ocr_tool = tesseract_ocr_tool = tts_model = None
        return False # 失敗

# ==============================================================================
# メインの実行ロジック (グローバルツールを使用)
# ==============================================================================
def main_ocr_process():
    """ 画面選択、Tesseractによる判定、OCRエンジンの切り替えを実行するメイン関数。 
        この関数はホットキーから呼び出され、OCR処理自体を実行します。
    """
    
    global capture_tool, easy_ocr_tool, tesseract_ocr_tool
    
    if capture_tool is None or easy_ocr_tool is None or tesseract_ocr_tool is None:
        print("❌ OCRツールが初期化されていません。処理を中止します。")
        return ""
        
    print("\n--- 処理開始 ---\n")
    print("🖱️ 画面上で範囲をドラッグして選択してください...")
    
    # 1. 画面領域の選択とキャプチャ
    coords = capture_tool.select_screen_area()
    
    if coords[0] == coords[2] or coords[1] == coords[3]:
        print("⚠️ 選択がキャンセルされたか、領域がゼロサイズです。処理を中止します。")
        return ""

    print(f"🖼️ 選択範囲: {coords}")

    image = capture_tool.capture_screen_area(coords)

    # 2. Tesseractで文字種判定
    print("\n🔎 Tesseractによる文字種判定を実行中...")
    is_handwriting, status_message = tesseract_ocr_tool.detect_writing_status(image)

    print(f"最終判定結果: {status_message}")

    final_text = ""
    
    # 3. 判定結果に基づきOCRエンジンを切り替え
    if is_handwriting:
        print("✍️ 手書き文字と判定されました。EasyOCRで詳細抽出します。")
        final_text = easy_ocr_tool.run_ocr(image)
    else:
        print("🖨️ 印刷文字と判定されました。Tesseract OCRで詳細抽出します。")
        final_text = tesseract_ocr_tool.run_ocr(image)
    
    #正規化
    final_text = _normalize_text(final_text)

    # 4. 英語→カタカナ変換（辞書ベース）
    if text_preprocessor is not None:
        try:
            processed_text = text_preprocessor.convert_english_to_katakana(final_text)
            if processed_text != final_text:
                print("\n--- 英語→カタカナ変換 ---")
                print(f"変換前: {final_text}")
                print(f"変換後: {processed_text}")
                print("--------------------------")
                final_text = processed_text
        except Exception as e:
            print(f"⚠️ テキスト変換エラー: {e}")

    # 5. 結果出力
    print("\n--- 抽出されたテキスト ---\n")
    # 不要な空白（スペース）を削除して表示
    print(final_text) 
    print("\n--------------------------")
    
    # 6. Style-Bert-VITS2で読み上げ
    if final_text and not final_text.startswith('[') and len(final_text.strip()) > 0:
        # 読み上げ前に改行と空白を整形
        text_to_speak = final_text
        speak_with_style_bert_vits2(text_to_speak)

    return final_text

# ==============================================================================
# ホットキーハンドラ (pynput用に変更)
# ==============================================================================
# pynputのロジックに合わせたラッパー関数 on_hotkey_action
def on_hotkey_action():
    """ ホットキーが押されたときに実行される関数。多重起動を防止し、メインOCRプロセスを呼び出します。 """
    global is_running
    if is_running:
        return
    
    is_running = True
    print("\n\n=============================================")
    # 出力メッセージを汎用的なものに修正
    print("▶️ Shift + F9 ホットキーが押されました。OCR開始")
    print("=============================================")
    try:
        main_ocr_process()
    except Exception as e:
        print(f"❌ 処理中に予期せぬエラーが発生しました: {e}")
    finally:
        is_running = False

# pynput.Listenerのコールバック関数に修正 (Shift + F9判定ロジックを導入)
def on_press(key):
    """ pynputのリスナーでキーが押されたときに呼び出される関数。 """
    global current_keys
    
    try:
        # 押されたキーを追跡セットに追加 (複合キー判定用)
        # Shift, Ctrl, Altなどの修飾キーもセットに保持
        current_keys.add(key)
        
        # 設定されたトリガーキー（F9）を検出
        if key == KEY_TO_TRIGGER:
            # Shiftキーが現在押されているかを確認
            # shift, shift_l, shift_rのいずれかがセットに含まれていればOK
            is_shift_pressed = (keyboard.Key.shift in current_keys or 
                                keyboard.Key.shift_l in current_keys or
                                keyboard.Key.shift_r in current_keys)
                            
            if is_shift_pressed:
                # Shift + F9 が成立
                on_hotkey_action()
    except AttributeError:
        # 特殊キーではない場合（a, b, 1など）は無視
        pass

# キーが離されたときに追跡セットから削除する関数
def on_release(key):
    """ キーが離されたときに呼び出される関数。追跡セットからキーを削除。 """
    global current_keys
    try:
        if key in current_keys:
            current_keys.remove(key)
    except Exception:
        pass # キーがセットにない場合は無視

# ==============================================================================
# アプリケーション起動関数 (pynput用に変更)
# ==============================================================================
def start_hotkey_ocr_app():
    """ アプリケーションの初期化、ホットキー登録、および実行ループを開始します。 """

    # 1. ツール初期化を関数として実行
    if not initialize_tools():
        print("🔴 初期化に失敗したため、ホットキーによる起動はできません。上記のエラーメッセージを確認してください。")
        return # 初期化失敗で終了

    # 2. ホットキーの設定
    print("\n--- ホットキー設定 ---")
    
    # ホットキーの表示名を "Shift + F9" に修正
    hotkey_name = "Shift + F9"
        
    print(f"キーボードの {hotkey_name} キーを押して、画面OCRを開始してください。")
    print("プログラムを終了するには Ctrl+C を押してください。")
    
    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
        
    except KeyboardInterrupt:
        print("\nプログラムを終了します。")
    except Exception as e:
        print(f"ホットキー監視中に予期せぬエラーが発生しました: {e}")

# Pythonのエントリーポイント
if __name__ == "__main__":
    # settings.iniから設定を読み込んで起動
    start_hotkey_ocr_app()
