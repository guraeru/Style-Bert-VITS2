# ハイブリッドOCR版 (Tesseract判定 + EasyOCR/Tesseract実行)
# Style-Bert-VITS2プロジェクト用OCR読み上げツール
import easyocr
import torch
import numpy as np
import cv2
from PIL import ImageGrab, Image 
import tkinter as tk
import pytesseract
from queue import Empty, Queue
from threading import Event, Lock, Thread
from pynput import keyboard 
import ctypes
from ctypes import windll
import sys
import os
from pathlib import Path
import configparser

# === マルチモニター対応: プロセスをDPI Awareにする ===
# これを設定しないとWindowsが座標を仮想的にスケーリングしてしまい、
# プライマリモニター以外での選択範囲やキャプチャ座標がズレる原因になる。
# Tkウィンドウなど、GUIを作成する前に一度だけ呼び出す必要がある。
def _set_dpi_awareness():
    try:
        # Per-Monitor DPI Aware V2 (Windows 10 1703以降で最も正確)
        windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return True
    except Exception:
        pass
    try:
        # Per-Monitor DPI Aware (Windows 8.1以降)
        windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        # System DPI Aware (フォールバック)
        windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False

_DPI_AWARE = _set_dpi_awareness()

# 仮想スクリーン（全モニターを含む領域）の座標・サイズを取得する定数
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

def get_virtual_screen_rect():
    """ 全モニターを合わせた仮想スクリーンの (x, y, width, height) を返す。
    サブモニターがプライマリモニターの左/上にある場合、x, yは負の値になり得る。 """
    user32 = windll.user32
    x = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    return x, y, w, h

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

# 吹き替えの音声生成と同じテキスト前処理を使用する。
from dubbing_tools.src.text_preprocessor import get_preprocessor

text_preprocessor = get_preprocessor()

scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100.0

def load_settings():
    """settings.iniから設定を読み込む"""
    config = configparser.ConfigParser()
    settings_path = _ocr_dir / "settings.ini"
    
    # デフォルト設定
    default_settings = {
        'TTS': {'model_name': 'ui_speaker', 'volume': '1.0'}
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

# 読み上げ音量（0.0〜1.0の範囲にクランプ）
try:
    VOLUME = settings.getfloat('TTS', 'volume', fallback=1.0)
except ValueError:
    print("⚠️ settings.iniのvolume値が不正です。デフォルト値(1.0)を使用します。")
    VOLUME = 1.0
VOLUME = max(0.0, min(1.0, VOLUME))

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
ocr_requests = Queue(maxsize=1)
state_lock = Lock()
speech_active = False
speech_cancelled = Event()

# 現在押されているキーを追跡するためのグローバルセット
current_keys = set() 

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

# ==============================================================================
# ユーティリティ関数
# ==============================================================================

def speak_with_style_bert_vits2(text_to_speak: str):
    """ Style-Bert-VITS2を使用してテキストを読み上げます。 """
    global speech_active
    
    if tts_model is None:
        print("⚠️ TTSモデルが初期化されていません。")
        return
    
    with state_lock:
        speech_cancelled.clear()
        speech_active = True

    tmp_path = None
    try:
        print(f"🔊 読み上げ中: {text_to_speak}")
        # 音声生成
        sr, audio = tts_model.infer(text=text_to_speak)
        if speech_cancelled.is_set():
            return
        
        # 一時ファイルに保存して再生
        import tempfile
        import soundfile as sf
        import pygame
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
        sf.write(tmp_path, audio, sr)
        
        # pygame で再生
        pygame.mixer.init()
        try:
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.set_volume(VOLUME)
            with state_lock:
                if speech_cancelled.is_set():
                    return
                pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if speech_cancelled.wait(0.05):
                    pygame.mixer.music.stop()
                    break
        finally:
            pygame.mixer.quit()
        
    except Exception as e:
        print(f"⚠️ TTS再生エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if tmp_path is not None:
                os.unlink(tmp_path)
        finally:
            with state_lock:
                speech_active = False

# ==============================================================================
# 画面選択とキャプチャ用クラス
# ==============================================================================
class ScreenCaptureTool:
    def select_screen_area(self):
        """ DPI対策と複数モニター対応を組み込んだ、スクリーン座標取得プロセス。
        '-fullscreen'属性はプライマリモニターにしか対応しないため使用せず、
        全モニターを合わせた仮想スクリーン全体にウィンドウを配置する。 """
        vx, vy, vw, vh = get_virtual_screen_rect()

        root = tk.Tk()
        try:
            # DPIスケールをリセット
            root.tk.call('tk', 'scaling', 1.0) 
        except Exception:
             pass 

        # 枠なしウィンドウを仮想スクリーン全体（全モニター）に配置
        root.overrideredirect(True)
        root.geometry(f"{vw}x{vh}+{vx}+{vy}")

        root.lift()
        root.attributes('-topmost', True) 
        root.attributes('-topmost', False) 
        root.attributes('-topmost', True) 

        root.attributes('-alpha', 0.3)
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

        # ウィンドウ内の相対座標(canvas座標)を仮想スクリーン上の絶対座標に変換
        if _DPI_AWARE:
            # プロセスがDPI Awareな場合、Tkの座標はそのまま物理ピクセルに対応する
            rel_x1, rel_y1 = min(start_x, end_x), min(start_y, end_y)
            rel_x2, rel_y2 = max(start_x, end_x), max(start_y, end_y)
        else:
            # フォールバック: 従来通りのDPIスケーリング補正（プライマリモニターのみ正確）
            rel_x1, rel_y1 = min(start_x, end_x) * scale_factor, min(start_y, end_y) * scale_factor
            rel_x2, rel_y2 = max(start_x, end_x) * scale_factor, max(start_y, end_y) * scale_factor

        x1, y1 = vx + rel_x1, vy + rel_y1
        x2, y2 = vx + rel_x2, vy + rel_y2

        return (int(x1), int(y1), int(x2), int(y2))

    def capture_screen_area(self, coords):
        """ 指定された画面領域をキャプチャし、OpenCV形式（BGR）の画像として返す。
        all_screens=True にすることで、プライマリモニター以外の領域や
        負の座標（サブモニターがプライマリの左/上にある場合）も正しくキャプチャできる。 """
        img = ImageGrab.grab(bbox=coords, all_screens=True)
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
                text = "\n".join([text for _, text, _ in results])
                
                
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

    # 3. 判定結果に基づきOCRエンジンを切り替え
    if is_handwriting:
        print("✍️ 手書き文字と判定されました。EasyOCRで詳細抽出します。")
        extracted_text = easy_ocr_tool.run_ocr(image)
    else:
        print("🖨️ 印刷文字と判定されました。Tesseract OCRで詳細抽出します。")
        extracted_text = tesseract_ocr_tool.run_ocr(image)

    print(f"\n--- 抽出されたテキスト ---\n{extracted_text}\n")
    if not extracted_text.strip() or extracted_text.startswith(
        ("[テキストが検出されませんでした]", "[OCR失敗")
    ):
        return extracted_text

    # SRT の entry.text と同じ前処理を、OCR の抽出結果に一度だけ適用する。
    text_to_speak = text_preprocessor.preprocess(extracted_text)
    if text_to_speak != extracted_text:
        print("\n--- 読み上げ用テキスト変換 ---")
        print(f"変換前: {extracted_text}")
        print(f"変換後: {text_to_speak}")
        print("--------------------------")
    if text_to_speak.strip():
        speak_with_style_bert_vits2(text_to_speak)

    return text_to_speak

# ==============================================================================
# ホットキーハンドラ (pynput用に変更)
# ==============================================================================
# pynputのロジックに合わせたラッパー関数 on_hotkey_action
def on_hotkey_action():
    """OCRを予約し、読み上げ中なら再生を中断する。"""
    global is_running
    with state_lock:
        if speech_active:
            speech_cancelled.set()
        elif is_running:
            return
        if ocr_requests.empty():
            ocr_requests.put_nowait(None)
        is_running = True

# pynput.Listenerのコールバック関数に修正 (Shift + F9判定ロジックを導入)
def on_press(key):
    """ pynputのリスナーでキーが押されたときに呼び出される関数。 """
    global current_keys
    
    try:
        # 押されたキーを追跡セットに追加 (複合キー判定用)
        # Shift, Ctrl, Altなどの修飾キーもセットに保持
        if key in current_keys:
            return
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
def run_ocr_requests(shutdown: Event):
    """同じスレッドで範囲選択と読み上げを順番に実行する。"""
    global is_running
    while not shutdown.is_set():
        try:
            ocr_requests.get(timeout=0.2)
        except Empty:
            continue
        if shutdown.is_set():
            return
        try:
            print("\n▶️ Shift + F9 ホットキーが押されました。OCR開始")
            main_ocr_process()
        except Exception as e:
            print(f"❌ 処理中に予期せぬエラーが発生しました: {e}")
        finally:
            with state_lock:
                is_running = not ocr_requests.empty()


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
    print(f"読み上げ中に {hotkey_name} を押すと、再生を停止して次の範囲選択を開始します。")
    print("プログラムを終了するには Ctrl+C を押してください。")
    
    shutdown = Event()
    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            Thread(target=run_ocr_requests, args=(shutdown,), daemon=True).start()
            listener.join()
        
    except KeyboardInterrupt:
        print("\nプログラムを終了します。")
    except Exception as e:
        print(f"ホットキー監視中に予期せぬエラーが発生しました: {e}")
    finally:
        shutdown.set()
        speech_cancelled.set()

# Pythonのエントリーポイント
if __name__ == "__main__":
    # settings.iniから設定を読み込んで起動
    start_hotkey_ocr_app()
