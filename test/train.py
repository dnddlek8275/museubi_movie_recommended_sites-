
import torch

from unsloth import FastLanguageModel

from datasets import load_dataset

from trl import SFTTrainer

from transformers import TrainingArguments

# 모델 설정

MODEL_NAME = "google/gemma-4-12b-it"

MAX_SEQ_LENGTH = 2048

DTYPE = None

LOAD_IN_4BIT = True

# 모델 로드

model, tokenizer = FastLanguageModel.from_pretrained(

    model_name=MODEL_NAME,

    max_seq_length=MAX_SEQ_LENGTH,

    dtype=DTYPE,

    load_in_4bit=LOAD_IN_4BIT,

)

# LoRA 설정

model = FastLanguageModel.get_peft_model(

    model,

    r=16,

    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",

                    "gate_proj", "up_proj", "down_proj"],

    lora_alpha=16,

    lora_dropout=0,

    bias="none",

    use_gradient_checkpointing="unsloth",

    random_state=42,

)

# 데이터 포맷

def format_prompt(example):

    return {

        "text": f"""<start_of_turn>user

{example['instruction']}

{example['input']}<end_of_turn>

<start_of_turn>model

{example['output']}<end_of_turn>"""

    }

# 데이터셋 로드

train_dataset = load_dataset("json", data_files="/home/elicer/cineverse/data/train_dataset.jsonl", split="train")

test_dataset  = load_dataset("json", data_files="/home/elicer/cineverse/data/test_dataset.jsonl",  split="train")

train_dataset = train_dataset.map(format_prompt)

test_dataset  = test_dataset.map(format_prompt)

print(f"Train: {len(train_dataset)}개")

print(f"Test : {len(test_dataset)}개")

print(f"샘플:\n{train_dataset[0]['text']}")

# 학습 설정

trainer = SFTTrainer(

    model=model,

    tokenizer=tokenizer,

    train_dataset=train_dataset,

    eval_dataset=test_dataset,

    dataset_text_field="text",

    max_seq_length=MAX_SEQ_LENGTH,

    dataset_num_proc=2,

    args=TrainingArguments(

        per_device_train_batch_size=2,

        gradient_accumulation_steps=4,

        warmup_steps=10,

        num_train_epochs=3,

        learning_rate=2e-4,

        fp16=not torch.cuda.is_bf16_supported(),

        bf16=torch.cuda.is_bf16_supported(),

        logging_steps=10,

        eval_strategy="steps",

        eval_steps=100,

        save_steps=200,

        save_total_limit=3,

        output_dir="/home/elicer/cineverse/output",

        report_to="none",

        optim="adamw_8bit",

        weight_decay=0.01,

        lr_scheduler_type="cosine",

        seed=42,

    ),

)

# 학습 시작

print("학습 시작!")

trainer.train()

# 모델 저장

model.save_pretrained("/home/elicer/cineverse/model/cineverse-gemma4")

tokenizer.save_pretrained("/home/elicer/cineverse/model/cineverse-gemma4")

print("모델 저장 완료!")

