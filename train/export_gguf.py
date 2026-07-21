"""
학습된 LoRA adapter → GGUF Q4_K_M 변환
Unsloth 내장 변환 기능 사용 (llama.cpp 불필요)
"""

import os
from pathlib import Path

BASE_MODEL   = "google/gemma-4-12b-it"
ADAPTER_DIR  = str(Path(__file__).parent.parent / "gemma4-cineverse-v2" / "final")
OUTPUT_DIR   = str(Path(__file__).parent.parent / "gemma4-cineverse-v2" / "gguf")

HF_TOKEN = os.environ.get("HF_TOKEN", "")

def main():
    from unsloth import FastLanguageModel

    print(f"[1/3] 베이스 모델 + LoRA 로드: {ADAPTER_DIR}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name     = ADAPTER_DIR,
        max_seq_length = 1024,
        dtype          = None,
        load_in_4bit   = True,
        token          = HF_TOKEN or None,
    )

    print(f"[2/3] GGUF Q4_K_M 변환 및 저장: {OUTPUT_DIR}")
    model.save_pretrained_gguf(
        OUTPUT_DIR,
        tokenizer,
        quantization_method = "q4_k_m",
    )

    gguf_files = list(Path(OUTPUT_DIR).glob("*.gguf"))
    print(f"[3/3] 완료! 생성된 파일:")
    for f in gguf_files:
        size_gb = f.stat().st_size / 1e9
        print(f"  {f}  ({size_gb:.1f} GB)")

    print("""
[NEXT] 메인 서버로 전송:
  메인 서버(210.109.15.251)에서:
    wget http://<클라우드IP>:<포트>/gemma4-cineverse-v2/gguf/*.gguf
  또는 클라우드에서 static 폴더에 복사 후 HTTP로 다운로드
""")

if __name__ == "__main__":
    main()
