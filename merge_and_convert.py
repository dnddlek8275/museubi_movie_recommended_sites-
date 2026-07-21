"""
LoRA 병합 + GGUF 변환 (메인 서버용)
mmap 해제 방법: 각 서브모듈의 _parameters/_buffers 딕셔너리를 직접 교체
→ 원본 mmap 텐서 refcount=0 → 파일 디스크립터 닫힘 → shutil.rmtree로 실제 디스크 회수
"""

import os, gc, shutil, subprocess
from pathlib import Path

HF_CACHE   = "/home/ubuntu/cineverse/hf-cache"
os.environ["HF_HOME"] = HF_CACHE  # transformers import 전에 설정

BASE_MODEL  = "google/gemma-4-12b-it"
LORA_PATH   = "/home/ubuntu/cineverse/lora-adapter"
MERGED_PATH = "/home/ubuntu/cineverse/gemma4-merged"
GGUF_OUT    = "/home/ubuntu/cineverse/gemma4-cineverse-v2.gguf"
CONVERT_PY  = "/home/ubuntu/cineverse/llama.cpp/convert_hf_to_gguf.py"

HF_TOKEN = os.environ.get("HF_TOKEN", "")
if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN 환경변수 필요: export HF_TOKEN=hf_...")


def disk_info(label):
    u = shutil.disk_usage("/home/ubuntu")
    print(f"  [{label}] 사용 {u.used/1e9:.1f}GB / 여유 {u.free/1e9:.1f}GB")


def release_mmaps(model):
    """각 서브모듈의 _parameters/_buffers를 clone으로 교체해 mmap fd를 닫는다."""
    import torch
    count = 0
    for module in model.modules():
        for name in list(module._parameters.keys()):
            p = module._parameters[name]
            if p is not None:
                module._parameters[name] = torch.nn.Parameter(
                    p.data.clone().contiguous(), requires_grad=False
                )
                count += 1
        for name in list(module._buffers.keys()):
            b = module._buffers[name]
            if b is not None:
                module._buffers[name] = b.clone().contiguous()
                count += 1
    print(f"  {count}개 텐서 클론 완료")


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    Path(HF_CACHE).mkdir(parents=True, exist_ok=True)

    # ── 1. 베이스 모델 다운로드 ───────────────────────────────
    print("[1/5] 베이스 모델 다운로드 (CPU bfloat16)...")
    disk_info("시작")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, token=HF_TOKEN)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, dtype=torch.bfloat16, device_map="cpu", token=HF_TOKEN
    )
    disk_info("다운로드 후")

    # ── 2. LoRA 병합 ─────────────────────────────────────────
    print("[2/5] LoRA 병합...")
    peft_model = PeftModel.from_pretrained(base_model, LORA_PATH)
    merged = peft_model.merge_and_unload()
    print("  병합 완료")

    # ── 3. mmap 해제 → HF 캐시 삭제 → 디스크 회수 ──────────
    print("[3/5] mmap 해제 중...")
    release_mmaps(merged)

    # PEFT 내부 참조 제거 후 GC
    del peft_model, base_model
    gc.collect()
    gc.collect()
    gc.collect()

    shutil.rmtree(HF_CACHE, ignore_errors=True)
    disk_info("캐시 삭제 후")  # 여기서 ~24GB 회복되어야 함

    # ── 4. 병합 모델 저장 ────────────────────────────────────
    print(f"[4/5] 병합 모델 저장: {MERGED_PATH}")
    Path(MERGED_PATH).mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(MERGED_PATH, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_PATH)
    del merged
    gc.collect()
    disk_info("저장 후")
    print("  저장 완료")

    # ── 5. GGUF Q4_K_M 변환 ──────────────────────────────────
    print(f"[5/5] GGUF 변환: {GGUF_OUT}")
    subprocess.run([
        "python3", CONVERT_PY,
        MERGED_PATH, "--outtype", "q4_k_m", "--outfile", GGUF_OUT,
    ], check=True)

    shutil.rmtree(MERGED_PATH, ignore_errors=True)
    size_gb = Path(GGUF_OUT).stat().st_size / 1e9
    print(f"\n완료! {GGUF_OUT} ({size_gb:.1f} GB)")
    print("llama-server를 새 GGUF 경로로 재시작하면 됩니다.")


if __name__ == "__main__":
    main()
