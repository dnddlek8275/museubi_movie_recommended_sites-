"""
CineVerse LLM 클라이언트 - llama-server OpenAI 호환
"""

from __future__ import annotations
import os
import requests

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8081")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-4-12b-it.Q4_K_M.gguf")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "300"))


def generate(messages: list[dict], max_tokens: int = 1024) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.15,
        "max_tokens": max_tokens,
        "stop": ["<end_of_turn>", "<end_of_/turn>", "<turn|>", "<|turn>"],
    }

    resp = requests.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=LLM_TIMEOUT,
    )

    if not resp.ok:
        print(f"  LLM 에러 {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 500:
            return ""
        resp.raise_for_status()

    data = resp.json()
    choice = data["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    return content