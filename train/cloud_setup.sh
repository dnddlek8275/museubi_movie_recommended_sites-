#!/bin/bash
# ============================================================
# CineVerse 클라우드 학습 환경 셋업 (엘리스 A100 20GB 기준)
# 이 스크립트를 클라우드 인스턴스에서 순서대로 실행하세요.
# ============================================================

set -e

echo "====== [1/5] 시스템 패키지 ======"
apt-get update -qq && apt-get install -y -qq git wget curl python3-pip nvtop

echo "====== [2/5] Python 환경 ======"
pip install -q --upgrade pip

# Unsloth (A100 전용 최적화 버전)
pip install -q "unsloth[cu124-torch250] @ git+https://github.com/unslothai/unsloth.git"

# 학습 라이브러리
pip install -q \
  trl==0.9.6 \
  transformers==4.46.3 \
  datasets==3.1.0 \
  accelerate==1.0.1 \
  bitsandbytes==0.44.1 \
  peft==0.13.2 \
  sentencepiece \
  protobuf

echo "====== [3/5] 프로젝트 파일 복사 ======"
# 현재 서버에서 학습 데이터와 스크립트를 클라우드로 복사하는 명령어
# 현재 서버(210.109.15.251)에서 실행:
#   scp -r ubuntu@<클라우드IP>:/data/  \
#       data/train_clean.jsonl \
#       data/train_multiturn.jsonl \
#       train/train_qlora.py \
#       gemma4-cineverse/checkpoint-3038/  # 기존 LoRA adapter

# 클라우드에서 직접 현재 서버에서 당겨올 경우:
# rsync -avz ubuntu@210.109.15.251:/home/ubuntu/cineverse/data/train_clean.jsonl .
# rsync -avz ubuntu@210.109.15.251:/home/ubuntu/cineverse/data/train_multiturn.jsonl .
# rsync -avz ubuntu@210.109.15.251:/home/ubuntu/cineverse/train/train_qlora.py .
# rsync -avz ubuntu@210.109.15.251:/home/ubuntu/cineverse/gemma4-cineverse/checkpoint-3038/ ./checkpoint-3038/

echo "====== [4/5] HuggingFace 로그인 ======"
# google/gemma-4-12b-it 다운로드를 위해 HF 토큰 필요
# https://huggingface.co/settings/tokens 에서 발급
# export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
huggingface-cli login --token "$HF_TOKEN"

echo "====== [5/5] GPU 확인 ======"
nvidia-smi
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB')"

echo ""
echo "====== 셋업 완료 ======"
echo "학습 시작: HF_TOKEN=\$HF_TOKEN python3 train_qlora.py"
