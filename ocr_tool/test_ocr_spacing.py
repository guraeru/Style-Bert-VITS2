import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "ocr_tool_module", Path(__file__).with_name("ocr_tool.py")
)
ocr_tool_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr_tool_module)


def test_normalize_ocr_speech_text_removes_ascii_spaces_after_preprocessing():
    assert ocr_tool_module.normalize_ocr_speech_text("原因 は 、OCR 後 の") == "原因は、オーシーアール後の"


def test_wrapped_japanese_matches_continuous_text_including_dictionary_readings():
    normalize = ocr_tool_module.normalize_ocr_speech_text
    assert normalize("技を伝\r\n　授する。\n日\t\n本へ。") == "技を伝授する。にほんへ。"


def test_invisible_layout_characters_do_not_interrupt_words_or_punctuation():
    normalize = ocr_tool_module.normalize_ocr_speech_text
    assert normalize("\ufeff手\u200b順は、\u2028ゆっ\u2060くり。\f") == "手順は、ゆっくり。"
    assert normalize("\ufeff\r\n　\u200b") == ""


def test_wrap_between_english_words_preserves_word_boundaries():
    normalize = ocr_tool_module.normalize_ocr_speech_text
    assert normalize("Ｂｒｕｓｈ\nＴｉｐ") == "ブラッシュティップ"
    assert normalize("qxzv\nzvqx") == "qxzv zvqx"
