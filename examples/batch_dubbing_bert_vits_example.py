"""
Style-BERT-VITS2を使ったバッチ吹き替え処理の実行例

フォルダー内のMP4とSRTファイルを自動検出して一括吹き替え処理を実行します。
このスクリプトはStyle-BERT-VITS2モデルを使用します。
"""

from pathlib import Path
import sys


# Style-Bert-VITS2のルートパスを追加
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    import os
    from dubbing_tools.batch_processor import create_batch_from_directory
    from dubbing_tools.dubbing_automation import DubbingAutomation
    
    # ========== 設定 ==========
    
    # 入力ディレクトリ（MP4とSRTファイルが入っているフォルダー）
    # バッチファイルから INPUT_DIR 環境変数で指定できます
    input_dir = os.environ.get("INPUT_DIR", "input_mp4")
    
    # 出力ディレクトリ
    # バッチファイルから OUTPUT_DIR 環境変数で指定できます
    output_dir = os.environ.get("OUTPUT_DIR", "output_mp4")
    
    # Style-BERT-VITS2モデル設定
    model_name = os.environ.get("MODEL_NAME", "jvnv-F1-jp")  # model_assets内のモデル名
    device = os.environ.get("DEVICE", "cuda")  # GPUを使用する場合は"cuda"、CPUの場合は"cpu"
    
    # サブディレクトリも検索するか
    recursive = True
    
    # ディレクトリ構造を保持するか（Trueなら入力と同じフォルダー構造で出力）
    preserve_structure = True
    
    # 出力ファイル名に追加するサフィックス
    suffix = "_dubbed"
    
    # 既に存在する出力ファイルをスキップするか
    skip_existing = True
    
    # 吹き替えオプション
    style = "Neutral"  # 感情スタイル
    style_weight = 1.0  # スタイルの強さ
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
    
    # DubbingAutomationを初期化
    print("\n🤖 モデルを読み込み中...")
    automation = DubbingAutomation(
        model_name=model_name,
        device=device,
    )
    
    # 各ファイルペアを処理
    print("\n🎬 バッチ処理を開始します...")
    print(f"  対象ファイル数: {len(video_paths)}個")
    
    completed = 0
    failed = 0
    
    for i, (video_path, srt_path, output_path) in enumerate(zip(video_paths, srt_paths, output_paths), 1):
        print(f"\n[{i}/{len(video_paths)}] {Path(video_path).name}")
        
        try:
            # 出力ディレクトリを作成
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # 吹き替え処理実行
            success = automation.create_dubbed_video(
                video_path=video_path,
                srt_path=srt_path,
                output_path=output_path,
                style=style,
                style_weight=style_weight,
                overlay=overlay,
                audio_volume=audio_volume,
                original_volume=original_volume,
                intro_only=intro_only,
            )
            
            if success:
                completed += 1
                print(f"✅ 完了: {Path(output_path).name}")
            else:
                failed += 1
                print(f"⚠️ 警告: {Path(output_path).name}")
                
        except Exception as e:
            failed += 1
            print(f"❌ エラー: {Path(video_path).name}")
            print(f"   詳細: {e}")
            continue
    
    # 結果表示
    print("\n" + "=" * 80)
    print("📊 バッチ処理結果")
    print("=" * 80)
    print(f"  合計: {len(video_paths)}個")
    print(f"  成功: {completed}個")
    print(f"  失敗: {failed}個")
    
    if completed > 0:
        print(f"\n✅ 出力先: {output_dir}")


if __name__ == "__main__":
    main()
