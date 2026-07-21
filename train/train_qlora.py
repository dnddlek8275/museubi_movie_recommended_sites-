"""
CineVerse Gemma-4 12B QLoRA 추가 학습 스크립트
Unsloth + HuggingFace Trainer 사용

변경점: SFTTrainer 대신 Trainer 사용 (VLM pickle 오류 우회)
데이터를 메인 프로세스에서 직접 토크나이징 → multiprocessing 없음
"""

import os
import json
import torch
from pathlib import Path
from datasets import Dataset
from transformers import TrainingArguments, DataCollatorForLanguageModeling, Trainer

# ── 설정 ─────────────────────────────────────────────────────
BASE_MODEL   = "google/gemma-4-12b-it"
LORA_ADAPTER = str(Path(__file__).parent.parent / "checkpoint-3038")
DATA_PATH    = Path(__file__).parent.parent / "data" / "train_clean.jsonl"
OUTPUT_DIR   = Path(__file__).parent.parent / "gemma4-cineverse-v2"

LORA_R       = 32
LORA_ALPHA   = 16
LORA_DROPOUT = 0.05
TARGET_MODS  = ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]

MAX_SEQ_LEN  = 1024
BATCH_SIZE   = 1
GRAD_ACCUM   = 16
EPOCHS       = 2
LR           = 2e-4
WARMUP_RATIO = 0.05

HF_TOKEN = os.environ.get("HF_TOKEN", "")

# ──────────────────────────────────────────────────────────────


def build_and_tokenize(path: Path, tokenizer, max_length: int) -> Dataset:
    """메인 프로세스에서 직접 토크나이징 — multiprocessing/pickle 없음.

    Gemma-4는 멀티모달 프로세서이므로 내부 텍스트 토크나이저를 직접 사용.
    """
    # Gemma4UnifiedProcessor → 내부 text tokenizer 추출
    text_tok = getattr(tokenizer, "tokenizer", tokenizer)

    records = [
        json.loads(l)
        for l in path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]

    input_ids_list = []
    for i, r in enumerate(records):
        if i % 5000 == 0:
            print(f"  토크나이징 {i}/{len(records)}...")

        convs = r["conversations"]
        text = ""
        for turn in convs:
            role = "model" if turn["role"] == "assistant" else "user"
            text += f"<start_of_turn>{role}\n{turn['content']}<end_of_turn>\n"
        text += "<eos>"

        enc = text_tok(text, max_length=max_length, truncation=True, padding=False)
        input_ids_list.append(enc["input_ids"])

    return Dataset.from_dict({
        "input_ids": input_ids_list,
        "labels":    [ids[:] for ids in input_ids_list],
    })


def main():
    # ── 1. Unsloth 모델 로드 ──────────────────────────────────
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name     = BASE_MODEL,
        max_seq_length = MAX_SEQ_LEN,
        dtype          = None,
        load_in_4bit   = True,
        token          = HF_TOKEN or None,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r                          = LORA_R,
        lora_alpha                 = LORA_ALPHA,
        lora_dropout               = LORA_DROPOUT,
        target_modules             = TARGET_MODS,
        bias                       = "none",
        use_gradient_checkpointing = "unsloth",
        random_state               = 42,
    )

    # 기존 체크포인트 가중치 주입
    adapter_path = Path(LORA_ADAPTER) / "adapter_model.safetensors"
    if adapter_path.exists():
        from peft import set_peft_model_state_dict
        import safetensors.torch as st
        state_dict = st.load_file(str(adapter_path))
        set_peft_model_state_dict(model, state_dict)
        print(f"[INFO] 기존 LoRA 가중치 로드 완료: {adapter_path}")
    else:
        print("[WARN] adapter_model.safetensors 없음 — 새 LoRA로 시작")

    # Gemma-4 멀티모달 프로세서 → 텍스트 토크나이저 추출
    text_tok = getattr(tokenizer, "tokenizer", tokenizer)
    if text_tok.pad_token is None:
        text_tok.pad_token = text_tok.eos_token

    # ── 2. 데이터셋 ──────────────────────────────────────────
    print(f"[INFO] 데이터 로드: {DATA_PATH}")
    dataset = build_and_tokenize(DATA_PATH, tokenizer, MAX_SEQ_LEN)  # text_tok 내부 추출
    split   = dataset.train_test_split(test_size=0.02, seed=42)
    print(f"[INFO] train={len(split['train'])} eval={len(split['test'])}")

    # ── 3. 학습 설정 ─────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    steps_per_epoch = len(split["train"]) // (BATCH_SIZE * GRAD_ACCUM)
    warmup_steps    = int(WARMUP_RATIO * steps_per_epoch * EPOCHS)

    args = TrainingArguments(
        output_dir                  = str(OUTPUT_DIR),
        num_train_epochs            = EPOCHS,
        per_device_train_batch_size = BATCH_SIZE,
        per_device_eval_batch_size  = BATCH_SIZE,
        gradient_accumulation_steps = GRAD_ACCUM,
        learning_rate               = LR,
        warmup_steps                = warmup_steps,
        lr_scheduler_type           = "cosine",
        bf16                        = True,
        fp16                        = False,
        optim                       = "adamw_8bit",
        logging_steps               = 50,
        eval_strategy               = "steps",
        eval_steps                  = 200,
        save_strategy               = "steps",
        save_steps                  = 500,
        save_total_limit            = 3,
        load_best_model_at_end      = False,
        report_to                   = "none",
        dataloader_num_workers      = 0,   # multiprocessing 완전 비활성화
        remove_unused_columns       = False,
        seed                        = 42,
    )

    # DataCollatorForLanguageModeling: 패딩 + labels 자동 처리 (text_tok 사용)
    collator = DataCollatorForLanguageModeling(tokenizer=text_tok, mlm=False)

    trainer = Trainer(
        model         = model,
        args          = args,
        train_dataset = split["train"],
        eval_dataset  = split["test"],
        data_collator = collator,
    )

    # ── 4. 학습 시작 ─────────────────────────────────────────
    print("[INFO] 학습 시작")
    trainer.train()

    # ── 5. 저장 ──────────────────────────────────────────────
    final_dir = OUTPUT_DIR / "final"
    model.save_pretrained(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))
    print(f"[INFO] LoRA adapter 저장: {final_dir}")

    print("""
[NEXT] LoRA → GGUF 변환 순서:
  1. LoRA 병합:
       python -c "
       from peft import PeftModel
       from transformers import AutoModelForCausalLM
       base = AutoModelForCausalLM.from_pretrained('google/gemma-4-12b-it', torch_dtype='bfloat16')
       model = PeftModel.from_pretrained(base, 'gemma4-cineverse-v2/final')
       model.merge_and_unload().save_pretrained('gemma4-cineverse-v2/merged')
       "
  2. llama.cpp 변환:
       python llama.cpp/convert_hf_to_gguf.py gemma4-cineverse-v2/merged --outtype q4_k_m
  3. 현재 서버에 복사 후 llama-server 재시작
""")


if __name__ == "__main__":
    main()
