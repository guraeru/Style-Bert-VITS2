#!/usr/bin/env python3
from style_bert_vits2.tts_model import TTSModelHolder
from config import get_path_config

path_config = get_path_config()
assets_root = path_config.assets_root

model_holder = TTSModelHolder(assets_root, 'cpu', '', ignore_onnx=True)

model_files = model_holder.model_files_dict.get('miyamae_moca', [])
if model_files:
    latest_file = str(model_files[0])
    model_holder.get_model('miyamae_moca', latest_file)
    
    if model_holder.current_model:
        model = model_holder.current_model
        print('Available styles:', list(model.style2id.keys()))
        print('Speaker2ID map:', list(model.spk2id.keys()))
