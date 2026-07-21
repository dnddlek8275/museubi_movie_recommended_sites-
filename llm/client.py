"""
CineVerse LLM Client
llama-server (OpenAI 호환) 호출 모듈
"""

import json
import os
import requests

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8081")
LLM_MODEL    = os.environ.get("LLM_MODEL", "gemma-4-12b-it.Q4_K_M.gguf")
LLM_TIMEOUT  = int(os.environ.get("LLM_TIMEOUT", "300"))

DEFAULT_PARAMS = {
    "temperature":    0.75,   # 0.7→0.75: 자기계발서 투 탈출, 약간 더 유연한 표현
    "top_p":          0.92,   # 0.9→0.92: 후보 토큰 풀 소폭 확대
    "top_k":          50,     # 40→50: 동일 목적
    "min_p":          0.05,
    "repeat_penalty": 1.1,    # 1.15→1.1: 과도한 반복 억제 완화 (자연스러운 반복 허용)
    "stop": ["<end_of_turn>", "<end_of_/turn>", "<turn|>", "<|turn>"],
}


def chat(
    messages: list[dict],
    max_tokens: int = 1024,
    **kwargs,
) -> str:
    """
    llama-server /v1/chat/completions 호출.

    Args:
        messages:   OpenAI 형식 메시지 리스트
        max_tokens: 최대 생성 토큰 수
        **kwargs:   temperature 등 파라미터 오버라이드

    Returns:
        생성된 텍스트 (content 필드)
    """
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        **DEFAULT_PARAMS,
        **kwargs,
    }

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/v1/chat/completions",
            json=payload,
            timeout=LLM_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"LLM 서버에 연결할 수 없습니다: {LLM_BASE_URL}")
    except requests.exceptions.Timeout:
        raise RuntimeError(f"LLM 서버 응답 시간 초과 ({LLM_TIMEOUT}s)")

    if not resp.ok:
        print(f"  [LLM] HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 500:
            return ""
        resp.raise_for_status()

    data    = resp.json()
    choice  = data["choices"][0]
    msg     = choice["message"]
    content = (msg.get("content") or "").strip()

    # --reasoning-budget 0 없이 기동된 경우 content가 비고 reasoning_content에 응답이 들어옴
    if not content:
        content = (msg.get("reasoning_content") or "").strip()
        if content:
            print("  [LLM] ⚠ content 비어있음 — reasoning_content로 fallback (--reasoning-budget 0 확인 필요)")

    finish = choice.get("finish_reason", "")
    if finish == "length":
        print(f"  [LLM] ⚠ finish=length — max_tokens({max_tokens}) 부족할 수 있음")

    return content


def chat_stream(
    messages: list[dict],
    max_tokens: int = 1024,
    **kwargs,
):
    """
    llama-server SSE 스트리밍 호출. 토큰이 생성될 때마다 yield.

    Yields:
        str: 생성된 토큰 조각
    """
    payload = {
        "model":  LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        **DEFAULT_PARAMS,
        **kwargs,
    }

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/v1/chat/completions",
            json=payload,
            timeout=LLM_TIMEOUT,
            stream=True,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"LLM 서버에 연결할 수 없습니다: {LLM_BASE_URL}")
    except requests.exceptions.Timeout:
        raise RuntimeError(f"LLM 서버 응답 시간 초과 ({LLM_TIMEOUT}s)")

    if not resp.ok:
        resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8")
        if decoded == "data: [DONE]":
            break
        if not decoded.startswith("data: "):
            continue
        try:
            chunk = json.loads(decoded[6:])
            delta = chunk["choices"][0]["delta"]
            token = delta.get("content") or delta.get("reasoning_content") or ""
            if token:
                yield token
        except (json.JSONDecodeError, KeyError):
            continue


def chat_json(
    messages: list[dict],
    max_tokens: int = 512,
    **kwargs,
) -> str:
    """
    JSON 응답을 기대하는 LLM 호출.
    temperature를 낮춰 일관성 확보.
    """
    return chat(
        messages,
        max_tokens=max_tokens,
        temperature=0.1,
        **kwargs,
    )
