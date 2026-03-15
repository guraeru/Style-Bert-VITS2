"""
バッチ処理モジュール

フォルダー内のMP4とSRTファイルをペアとして自動検出し、一括で吹き替え処理を実行します。
MP4とSRTが同じフォルダーに入っている構造に対応しています。
"""

import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# 除外対象フォルダー（先頭に含まれる名前でフィルタリング）
EXCLUDED_FOLDERS = {"[CV宮舞モカ]"}


@dataclass
class VideoSRTPair:
    """動画とSRTファイルのペア"""
    video_path: str
    srt_path: str  # コピーのみの場合は空文字列
    relative_path: str  # 入力ルートからの相対パス（出力先決定用）
    copy_only: bool = False  # Trueの場合、吹き替えせずそのままコピー
    
    def __repr__(self):
        label = "copy" if self.copy_only else "dub"
        return f"VideoSRTPair({Path(self.video_path).name}, {label})"


def _is_excluded_folder(folder_path: Path) -> bool:
    """
    フォルダーが除外対象かチェック
    
    パスの各部分について、除外対象フォルダーの名前で始まるかを確認します。
    
    Args:
        folder_path: チェック対象のフォルダーパス
        
    Returns:
        除外対象ならTrue、そうでなければFalse
    """
    for part in folder_path.parts:
        for excluded in EXCLUDED_FOLDERS:
            if part.startswith(excluded):
                return True
    return False


def _get_dirs_with_srt(input_path: Path, recursive: bool) -> set:
    """
    SRTファイルが1つでも存在するディレクトリの集合を返す。
    
    あるディレクトリにSRTがあれば、そのディレクトリは「翻訳対象の講座」とみなし、
    字幕なし動画も含めて全動画を処理対象とする。
    
    除外対象フォルダーに含まれるSRTは対象外とします。
    """
    if recursive:
        srt_files = list(input_path.rglob("*.srt"))
    else:
        srt_files = list(input_path.glob("*.srt"))
    
    return {str(srt.parent) for srt in srt_files if not _is_excluded_folder(srt.parent)}


def find_video_srt_pairs(
    input_dir: str,
    recursive: bool = True,
    video_extensions: List[str] = None,
    include_copy_only: bool = True,
) -> List[VideoSRTPair]:
    """
    指定ディレクトリ内のMP4とSRTファイルをペアとして検出
    
    講座判定ロジック:
    - ディレクトリ内に1つでもSRTファイルがあれば「翻訳対象の講座」とみなす
    - SRTのある動画 → 吹き替え処理対象
    - SRTのない動画（同講座内） → そのままコピー対象
    - SRTが1つもないディレクトリ → 日本語講座として丸ごと無視
    
    Args:
        input_dir: 検索するディレクトリ
        recursive: サブディレクトリも検索するか
        video_extensions: 対応する動画ファイル拡張子のリスト
        include_copy_only: 字幕なし動画もコピー対象として含めるか
        
    Returns:
        検出されたペアのリスト（copy_only=Trueのエントリ含む）
    """
    if video_extensions is None:
        video_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv']
    
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"入力ディレクトリが見つかりません: {input_dir}")
    
    # SRTファイルが存在するディレクトリの集合を取得
    dirs_with_srt = _get_dirs_with_srt(input_path, recursive)
    
    pairs = []
    
    # 動画ファイルを検索
    if recursive:
        video_files = []
        for ext in video_extensions:
            video_files.extend(input_path.rglob(f"*{ext}"))
    else:
        video_files = []
        for ext in video_extensions:
            video_files.extend(input_path.glob(f"*{ext}"))
    
    # 各動画ファイルを処理
    for video_file in video_files:
        # 除外対象フォルダーかチェック
        if _is_excluded_folder(video_file.parent):
            continue
        
        video_dir = str(video_file.parent)
        
        # このディレクトリにSRTが1つもなければスキップ（日本語講座）
        if video_dir not in dirs_with_srt:
            continue
        
        # 入力ルートからの相対パスを取得
        try:
            relative = video_file.relative_to(input_path)
        except ValueError:
            relative = video_file.name
        
        # 同名のSRTファイルを探す
        srt_file = video_file.with_suffix('.srt')
        
        if srt_file.exists():
            # SRTあり → 吹き替え対象
            pair = VideoSRTPair(
                video_path=str(video_file),
                srt_path=str(srt_file),
                relative_path=str(relative),
                copy_only=False,
            )
            pairs.append(pair)
        elif include_copy_only:
            # SRTなし、でも同講座内 → コピー対象
            pair = VideoSRTPair(
                video_path=str(video_file),
                srt_path="",
                relative_path=str(relative),
                copy_only=True,
            )
            pairs.append(pair)
    
    return pairs


def create_output_paths(
    pairs: List[VideoSRTPair],
    output_dir: str,
    preserve_structure: bool = True,
    suffix: str = "_dubbed",
) -> List[str]:
    """
    出力パスのリストを生成
    
    Args:
        pairs: 動画とSRTのペアのリスト
        output_dir: 出力ディレクトリ
        preserve_structure: ディレクトリ構造を保持するか
        suffix: 出力ファイル名に追加するサフィックス
        
    Returns:
        出力パスのリスト
    """
    output_path = Path(output_dir)
    output_paths = []
    
    for pair in pairs:
        if preserve_structure:
            # 相対パスを保持
            relative_path = Path(pair.relative_path)
            output_file = output_path / relative_path.parent / f"{relative_path.stem}{suffix}{relative_path.suffix}"
        else:
            # すべてのファイルを出力ディレクトリ直下に配置
            video_name = Path(pair.video_path).name
            output_file = output_path / f"{Path(video_name).stem}{suffix}{Path(video_name).suffix}"
        
        output_paths.append(str(output_file))
    
    return output_paths


def print_batch_summary(pairs: List[VideoSRTPair], output_paths: List[str]) -> None:
    """
    バッチ処理のサマリーを表示
    
    Args:
        pairs: 動画とSRTのペアのリスト
        output_paths: 出力パスのリスト
    """
    dub_count = sum(1 for p in pairs if not p.copy_only)
    copy_count = sum(1 for p in pairs if p.copy_only)
    
    print("\n" + "=" * 80)
    print(f"バッチ処理サマリー: {len(pairs)}個のファイルを検出")
    print(f"  吹き替え: {dub_count}個 / コピーのみ: {copy_count}個")
    print("=" * 80)
    
    for i, (pair, output) in enumerate(zip(pairs, output_paths), 1):
        mode = "📋 コピー" if pair.copy_only else "🎤 吹き替え"
        print(f"\n[{i}/{len(pairs)}] {mode}")
        print(f"  動画: {pair.video_path}")
        if not pair.copy_only:
            print(f"  字幕: {pair.srt_path}")
        print(f"  出力: {output}")


def filter_existing_outputs(
    pairs: List[VideoSRTPair],
    output_paths: List[str],
    skip_existing: bool = False,
) -> Tuple[List[VideoSRTPair], List[str]]:
    """
    既に存在する出力ファイルをフィルタリング
    
    Args:
        pairs: 動画とSRTのペアのリスト
        output_paths: 出力パスのリスト
        skip_existing: 既存ファイルをスキップするか
        
    Returns:
        フィルタリング後のペアと出力パスのタプル
    """
    if not skip_existing:
        return pairs, output_paths
    
    filtered_pairs = []
    filtered_outputs = []
    
    for pair, output in zip(pairs, output_paths):
        if not os.path.exists(output):
            filtered_pairs.append(pair)
            filtered_outputs.append(output)
        else:
            print(f"スキップ（既に存在）: {output}")
    
    return filtered_pairs, filtered_outputs


def group_pairs_by_directory(pairs: List[VideoSRTPair]) -> Dict[str, List[VideoSRTPair]]:
    """
    ペアをディレクトリごとにグループ化
    
    Args:
        pairs: 動画とSRTのペアのリスト
        
    Returns:
        ディレクトリパスをキーとした辞書
    """
    groups = {}
    
    for pair in pairs:
        dir_path = str(Path(pair.video_path).parent)
        if dir_path not in groups:
            groups[dir_path] = []
        groups[dir_path].append(pair)
    
    return groups


def create_batch_from_directory(
    input_dir: str,
    output_dir: str,
    recursive: bool = True,
    preserve_structure: bool = True,
    suffix: str = "_dubbed",
    skip_existing: bool = False,
) -> Tuple[List[str], List[str], List[str], List[bool]]:
    """
    ディレクトリからバッチ処理用のパスリストを生成
    
    講座判定: ディレクトリ内に1つでもSRTがあれば翻訳対象講座とみなし、
    字幕なし動画もコピー対象として含めます。SRTが一切ないディレクトリは無視します。
    
    Args:
        input_dir: 入力ディレクトリ
        output_dir: 出力ディレクトリ
        recursive: サブディレクトリも検索するか
        preserve_structure: ディレクトリ構造を保持するか
        suffix: 出力ファイル名に追加するサフィックス
        skip_existing: 既存ファイルをスキップするか
        
    Returns:
        (video_paths, srt_paths, output_paths, copy_only_flags)のタプル
    """
    # ペアを検出（字幕なし動画も含む）
    pairs = find_video_srt_pairs(input_dir, recursive=recursive, include_copy_only=True)
    
    if not pairs:
        print(f"⚠️ 処理対象の動画が見つかりませんでした: {input_dir}")
        return [], [], [], []
    
    # 出力パスを生成
    output_paths = create_output_paths(
        pairs,
        output_dir,
        preserve_structure=preserve_structure,
        suffix=suffix,
    )
    
    # 既存ファイルをフィルタリング
    pairs, output_paths = filter_existing_outputs(
        pairs,
        output_paths,
        skip_existing=skip_existing,
    )
    
    if not pairs:
        print("ℹ️ 処理対象のファイルがありません（すべて既に存在）")
        return [], [], [], []
    
    # サマリー表示
    print_batch_summary(pairs, output_paths)
    
    # パスリストを抽出
    video_paths = [pair.video_path for pair in pairs]
    srt_paths = [pair.srt_path for pair in pairs]
    copy_only_flags = [pair.copy_only for pair in pairs]
    
    return video_paths, srt_paths, output_paths, copy_only_flags
