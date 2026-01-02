"""
吹き替え自動化ツールの使用例

このスクリプトはStyle-Bert-VITS2の吹き替え自動化ツールの使用方法を示します。

元のmp4_editコードを参考に、動画と音声の結合処理を実装しています。
"""

from pathlib import Path
from dubbing_tools import DubbingAutomation
import os


def example_basic():
    """
    基本的な使用例
    
    1つの動画とSRTファイルから吹き替え動画を作成します。
    
    フォルダ構成:
    - input_mp4/srt/video1.srt
    - input_mp4/講座A/video1.mp4
    - output_mp4/講座A/video1.mp4 (出力)
    """
    # モデル設定
    model_name = "your_model_name"  # 使用するモデル名
    model_path = "model_assets/your_model_name/your_model_name_e100_s1000.safetensors"
    config_path = "model_assets/your_model_name/config.json"
    style_vec_path = "model_assets/your_model_name/style_vectors.npy"
    
    # 吹き替え自動化クラス初期化
    dubbing = DubbingAutomation(
        model_name=model_name,
        model_path=model_path,
        config_path=config_path,
        style_vec_path=style_vec_path,
        device="cuda",  # GPUを使用(CPUの場合は"cpu")
        tolerance_seconds=60.0,  # 許容超過時間(秒)
    )
    
    # 吹き替え動画作成
    dubbing.create_dubbed_video(
        video_path="input_mp4/講座A/video1.mp4",
        srt_path="input_mp4/srt/video1.srt",
        output_path="output_mp4/講座A/video1.mp4",
        style="Neutral",  # 感情スタイル
        style_weight=1.0,
        overlay=True,  # 元の音声に重ねる
        audio_volume=1.0,  # 生成音声の音量
        original_volume=0.3,  # 元の音声の音量(overlayがTrueの場合のみ)
    )


def example_custom_settings():
    """
    カスタム設定の例
    
    より細かい設定をカスタマイズします。
    """
    # ffmpegのパスを指定(デフォルトはPATH上のffmpeg)
    dubbing = DubbingAutomation(
        model_name="your_model_name",
        model_path="model_assets/your_model_name/model.safetensors",
        config_path="model_assets/your_model_name/config.json",
        style_vec_path="model_assets/your_model_name/style_vectors.npy",
        device="cuda",
        ffmpeg_path="C:/ffmpeg/bin/ffmpeg.exe",  # カスタムパス
        tolerance_seconds=30.0,  # 許容超過時間を30秒に設定
        min_length_scale=0.6,  # 最速1.67倍速まで許可
    )
    
    # 元の音声を完全に置き換える
    dubbing.create_dubbed_video(
        video_path="input/video.mp4",
        srt_path="input/subtitles.srt",
        output_path="output/dubbed.mp4",
        overlay=False,  # 置き換えモード
        audio_volume=1.0,
    )


def example_batch_processing():
    """
    バッチ処理の例
    
    複数の動画を一括で処理します。
    
    フォルダ構成:
    - input_mp4/srt/*.srt
    - input_mp4/講座A/*.mp4
    - output_mp4/講座A/*.mp4 (出力)
    """
    # モデル初期化(1回だけ)
    dubbing = DubbingAutomation(
        model_name="your_model_name",
        model_path="model_assets/your_model_name/model.safetensors",
        config_path="model_assets/your_model_name/config.json",
        style_vec_path="model_assets/your_model_name/style_vectors.npy",
        device="cuda",
        tolerance_seconds=60.0,
    )
    
    # 動画リスト
    videos = [
        ("input_mp4/講座A/video1.mp4", "input_mp4/srt/video1.srt", "output_mp4/講座A/video1.mp4"),
        ("input_mp4/講座A/video2.mp4", "input_mp4/srt/video2.srt", "output_mp4/講座A/video2.mp4"),
        ("input_mp4/講座B/video3.mp4", "input_mp4/srt/video3.srt", "output_mp4/講座B/video3.mp4"),
    ]
    
    # 一括処理
    for video_path, srt_path, output_path in videos:
        try:
            print(f"\n{'='*60}")
            print(f"処理中: {video_path}")
            print(f"{'='*60}")
            
            dubbing.create_dubbed_video(
                video_path=video_path,
                srt_path=srt_path,
                output_path=output_path,
                style="Neutral",
                overlay=True,
                audio_volume=1.0,
                original_volume=0.3,
            )
            
            print(f"✅ 完了: {output_path}\n")
        except Exception as e:
            print(f"❌ エラー: {video_path} - {e}\n")
            continue


def example_style_variations():
    """
    複数のスタイルで生成する例
    
    同じ動画を異なる感情スタイルで複数生成します。
    """
    dubbing = DubbingAutomation(
        model_name="your_model_name",
        model_path="model_assets/your_model_name/model.safetensors",
        config_path="model_assets/your_model_name/config.json",
        style_vec_path="model_assets/your_model_name/style_vectors.npy",
        device="cuda",
    )
    
    # 異なるスタイルで生成
    styles = ["Neutral", "Happy", "Sad", "Angry"]
    
    for style in styles:
        output_path = f"output/dubbed_{style.lower()}.mp4"
        
        dubbing.create_dubbed_video(
            video_path="input/video.mp4",
            srt_path="input/subtitles.srt",
            output_path=output_path,
            style=style,
            style_weight=1.0,
            overlay=True,
        )


def example_with_existing_structure():
    """
    新しいフォルダ構造に対応した例
    
    フォルダ構成:
    - input_mp4/srt/video.srt
    - input_mp4/動画フォルダー/video.mp4
    - output_mp4/動画フォルダー/video.mp4 (出力先)
    """
    # ファイルペアを検索
    input_base = "input_mp4"
    output_base = "output_mp4"
    srt_folder = os.path.join(input_base, "srt")
    file_pairs = []
    
    # input_mp4内のすべてのサブフォルダを検索
    for root, dirs, files in os.walk(input_base):
        # srtフォルダはスキップ
        if "srt" in root:
            continue
            
        for file in files:
            if file.endswith('.mp4'):
                video_path = os.path.join(root, file)
                name = file.rsplit('.', 1)[0]
                
                # 対応するSRTファイルを探す
                srt_path = os.path.join(srt_folder, f"{name}.srt")
                
                if os.path.exists(srt_path):
                    # 出力先: input_mp4/動画フォルダー → output_mp4/動画フォルダー
                    relative_path = os.path.relpath(video_path, input_base)
                    output_path = os.path.join(output_base, relative_path)
                    file_pairs.append((video_path, srt_path, output_path))
    
    # モデル初期化
    dubbing = DubbingAutomation(
        model_name="your_model_name",
        model_path="model_assets/your_model_name/model.safetensors",
        config_path="model_assets/your_model_name/config.json",
        style_vec_path="model_assets/your_model_name/style_vectors.npy",
        device="cuda",
    )
    
    # 一括処理
    for video_path, srt_path, output_path in file_pairs:
        print(f"\n処理中: {video_path}")
        try:
            dubbing.create_dubbed_video(
                video_path=video_path,
                srt_path=srt_path,
                output_path=output_path,
                overlay=True,
                audio_volume=1.0,
                original_volume=0.3,
            )
            print(f"✅ 完了: {output_path}")
        except Exception as e:
            print(f"❌ エラー: {e}")


if __name__ == "__main__":
    # 使用例を選択して実行
    print("吹き替え自動化ツール - 使用例")
    print("\n1. 基本的な使用例")
    print("2. カスタム設定の例")
    print("3. バッチ処理の例")
    print("4. スタイル違いで複数生成")
    print("5. 既存のフォルダ構造で一括処理")
    
    choice = input("\n実行する例を選択してください (1-5): ")
    
    if choice == "1":
        example_basic()
    elif choice == "2":
        example_custom_settings()
    elif choice == "3":
        example_batch_processing()
    elif choice == "4":
        example_style_variations()
    elif choice == "5":
        example_with_existing_structure()
    else:
        print("無効な選択です")
