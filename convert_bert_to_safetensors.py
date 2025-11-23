"""
PyTorch形式のBERTモデルをSafeTensors形式に変換するスクリプト
"""
import os
from pathlib import Path
import torch
from safetensors.torch import save_file

def convert_pytorch_to_safetensors(model_dir: str):
    """
    指定されたディレクトリ内のpytorch_model.binをmodel.safetensorsに変換する
    """
    model_dir = Path(model_dir)
    pytorch_model_path = model_dir / "pytorch_model.bin"
    safetensors_path = model_dir / "model.safetensors"
    
    if not pytorch_model_path.exists():
        print(f"Skipping {model_dir}: pytorch_model.bin not found")
        return False
    
    if safetensors_path.exists():
        print(f"Skipping {model_dir}: model.safetensors already exists")
        return False
    
    print(f"Converting {pytorch_model_path} to SafeTensors format...")
    try:
        # PyTorchモデルを読み込む (weights_only=Falseで古い形式も読める)
        state_dict = torch.load(pytorch_model_path, map_location="cpu", weights_only=False)
        
        # すべてのテンソルを連続メモリに変換し、共有メモリの問題を解決
        print("  Making all tensors contiguous...")
        for key in list(state_dict.keys()):
            if torch.is_tensor(state_dict[key]):
                # 非連続テンソルを連続にする
                if not state_dict[key].is_contiguous():
                    state_dict[key] = state_dict[key].contiguous()
                # 共有されている可能性があるテンソルをクローン
                state_dict[key] = state_dict[key].clone()
        
        # SafeTensors形式で保存
        save_file(state_dict, str(safetensors_path))
        
        print(f"Successfully converted: {safetensors_path}")
        return True
    except Exception as e:
        print(f"Error converting {pytorch_model_path}: {e}")
        return False

if __name__ == "__main__":
    bert_dir = Path("bert")
    
    if not bert_dir.exists():
        print("bert directory not found!")
        exit(1)
    
    # bert ディレクトリ内のすべてのサブディレクトリを検索
    converted_count = 0
    for model_subdir in bert_dir.iterdir():
        if model_subdir.is_dir() and not model_subdir.name.endswith("-onnx"):
            if convert_pytorch_to_safetensors(model_subdir):
                converted_count += 1
    
    print(f"\nConversion complete! {converted_count} model(s) converted.")
