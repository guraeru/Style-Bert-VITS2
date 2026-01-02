"""
バッチ吹き替え処理の実行例

フォルダー内のMP4とSRTファイルを自動検出して一括吹き替え処理を実行します。
"""

import os
from pathlib import Path
from dubbing_tools.batch_processor import create_batch_from_directory
from dubbing_tools.pipeline_processor import PipelineProcessor, create_dubbing_tasks


def main():
    # ========== 設定 ==========
    
    # 入力ディレクトリ（MP4とSRTファイルが入っているフォルダー）
    # バッチファイルから INPUT_DIR 環境変数で指定できます
    input_dir = os.environ.get("INPUT_DIR", "input_mp4")
    
    # 出力ディレクトリ
    # バッチファイルから OUTPUT_DIR 環境変数で指定できます
    output_dir = os.environ.get("OUTPUT_DIR", "output_mp4")
    
    # サブディレクトリも検索するか
    recursive = True
    
    # ディレクトリ構造を保持するか（Trueなら入力と同じフォルダー構造で出力）
    preserve_structure = True
    
    # 出力ファイル名に追加するサフィックス
    suffix = "_dubbed"
    
    # 既に存在する出力ファイルをスキップするか
    skip_existing = True
    
    # VOICEPEAK設定
    voicepeak_path = r"C:\Program Files\VOICEPEAK\voicepeak.exe"
    narrator = os.environ.get("NARRATOR", "Japanese Female Child 1")  # VOICEPEAKのナレーター名
    emotion = None  # 感情設定（Noneなら標準）
    pitch = 0  # ピッチ調整（-300 ~ 300）
    
    # 吹き替えオプション
    overlay = True  # Trueなら元の音声に重ねる、Falseなら置き換える
    audio_volume = 1.0  # 生成音声の音量
    original_volume = 0.3  # 元の音声の音量（overlayがTrueの場合のみ）
    intro_only = False  # Trueならイントロ部分のみ元の音声を重ねる
    
    # =========================
    
    # バッチ処理用のパスリストを生成
    print("📂 ファイルペアを検索中...")
    video_paths, srt_paths, output_paths = create_batch_from_directory(
        input_dir=input_dir,
        output_dir=output_dir,
        recursive=recursive,
        preserve_structure=preserve_structure,
        suffix=suffix,
        skip_existing=skip_existing,
    )
    
    if not video_paths:
        print("処理対象のファイルがありません。")
        return
    
    # タスクを作成
    tasks = create_dubbing_tasks(
        video_paths=video_paths,
        srt_paths=srt_paths,
        output_paths=output_paths,
        overlay=overlay,
        audio_volume=audio_volume,
        original_volume=original_volume,
        intro_only=intro_only,
    )
    
    # パイプライン処理実行
    print("\n🎬 バッチ処理を開始します...")
    print(f"  対象ファイル数: {len(tasks)}個")
    
    processor = PipelineProcessor(
        voicepeak_path=voicepeak_path,
        narrator=narrator,
        emotion=emotion,
        pitch=pitch,
    )
    
    # 進捗表示用コールバック
    def progress_callback(task):
        if task.status.value == "completed":
            print(f"✅ 完了: {Path(task.output_path).name}")
        elif task.status.value == "failed":
            print(f"❌ 失敗: {Path(task.video_path).name} - {task.error}")
    
    processor.progress_callback = progress_callback
    
    # 処理実行
    result = processor.process_batch(tasks)
    
    # 結果表示
    print("\n" + "=" * 80)
    print("📊 バッチ処理結果")
    print("=" * 80)
    print(f"  合計: {result['total']}個")
    print(f"  成功: {result['completed']}個")
    print(f"  失敗: {result['failed']}個")
    print(f"  処理時間: {result['total_time']:.1f}秒")
    
    # 失敗したタスクの詳細を表示
    if result['failed'] > 0:
        print("\n❌ 失敗したタスク:")
        for task in result['tasks']:
            if task.status.value == "failed":
                print(f"  - {Path(task.video_path).name}: {task.error}")


if __name__ == "__main__":
    main()
