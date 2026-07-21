"""
CineVerse FastAPI AI API

엔드포인트:
    GET  /health          - 서버 상태
    POST /chat            - 캐릭터 1:1 대화
    POST /chat/group      - 캐릭터 그룹 채팅
    POST /chat/group/auto - 인텐트 자동 분류 후 그룹 채팅 (영화 추천 포함)
    POST /recommend       - 영화 추천
    POST /chat/auto       - 인텐트 자동 분류 후 라우팅
    POST /chat/stream     - 스트리밍 캐릭터 대화 (SSE)
"""

from __future__ import annotations
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline.intent import classify, Intent
from pipeline.character_pipeline import (
    run as character_run,
    run_auto as character_auto_run,
    run_group,
    run_group_rounds,
    run_group_auto_rounds,
    resolve_character_names,
)
from pipeline.movie_pipeline import run as movie_run

app = FastAPI(title="CineVerse AI API", version="2.0.0")


@app.on_event("startup")
async def warmup():
    """서버 시작 시 BGE-M3 임베더 + CrossEncoder 리랭커를 미리 로드."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _load_models)


def _load_models():
    from rag.embedder import get_embedder
    from rag.reranker import get_reranker
    print("[Warmup] BGE-M3 임베더 로드 중...")
    get_embedder()
    print("[Warmup] CrossEncoder 리랭커 로드 중...")
    get_reranker()
    print("[Warmup] 완료 — 첫 요청부터 즉시 응답 가능")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 학습 파일 임시 다운로드용 (전송 후 제거 예정)
import os as _os
_static_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "static")
if _os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ── 요청 스키마 ──

class ChatRequest(BaseModel):
    character:  str
    message:    str
    history:    list[dict] = []
    use_rag:    bool = True

class GroupChatRequest(BaseModel):
    characters: list[str]
    message:    str
    history:    list[dict] = []

class RecommendRequest(BaseModel):
    message:    str
    character:  Optional[str] = None
    history:    list[dict] = []
    genre:      Optional[str] = None
    actor:      Optional[str] = None
    director:   Optional[str] = None
    language:   Optional[str] = None
    year_from:  Optional[int] = None
    year_to:    Optional[int] = None
    min_rating: Optional[float] = None

class AutoRequest(BaseModel):
    character:  Optional[str] = None
    message:    str
    history:    list[dict] = []


# ── 응답 스키마 ──

class ChatResponse(BaseModel):
    character:    str
    answer:       str
    finish_reason: str = "stop"
    rag_used:     bool = False

class GroupChatResponse(BaseModel):
    responses: list[ChatResponse]

class RoundResponse(BaseModel):
    round:     int
    label:     str
    responses: list[ChatResponse]

class GroupRoundsResponse(BaseModel):
    rounds: list[RoundResponse]

class GroupAutoRoundsResponse(BaseModel):
    intent: str
    movies: list[dict] = []
    rounds: list[RoundResponse]

class RecommendResponse(BaseModel):
    answer: str
    movies: list[dict]

class AutoResponse(BaseModel):
    intent:    str
    character: str
    answer:    str
    movies:    list[dict] = []


# ── 헬스체크 ──

@app.get("/health")
def health():
    import requests as _req
    from pymilvus import MilvusClient

    components: dict = {}

    # llama-server
    try:
        r = _req.get("http://localhost:8081/health", timeout=3)
        components["llm"] = "ok" if r.ok else f"error:{r.status_code}"
    except Exception as e:
        components["llm"] = f"down:{e}"

    # Milvus
    try:
        mc = MilvusClient(uri="http://localhost:19530")
        cols = mc.list_collections()
        components["milvus"] = f"ok ({len(cols)} collections)"
    except Exception as e:
        components["milvus"] = f"down:{e}"

    # 임베더 (로드 여부)
    try:
        from rag.embedder import get_embedder
        get_embedder()
        components["embedder"] = "ok"
    except Exception as e:
        components["embedder"] = f"error:{e}"

    overall = "ok" if all(v.startswith("ok") for v in components.values()) else "degraded"
    return {"status": overall, "version": "2.0.0", "components": components}


# ── 1:1 캐릭터 대화 ──

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        result = character_run(
            character_name=req.character,
            user_message=req.message,
            history=req.history,
            use_rag=req.use_rag,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"캐릭터 '{req.character}'를 찾을 수 없습니다.")

    return ChatResponse(
        character=result.character,
        answer=result.answer,
        rag_used=result.rag_used,
    )


# ── 그룹 채팅 ──

@app.post("/chat/group", response_model=GroupChatResponse)
def chat_group(req: GroupChatRequest):
    if not 2 <= len(req.characters) <= 5:
        raise HTTPException(status_code=400, detail="캐릭터는 2~5명이어야 합니다.")

    try:
        results = run_group(
            characters=req.characters,
            user_message=req.message,
            history=req.history,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip('"'))

    return GroupChatResponse(
        responses=[
            ChatResponse(character=r.character, answer=r.answer)
            for r in results
        ]
    )


# ── 그룹 채팅 (2라운드 반응형) ──

@app.post("/chat/group/rounds", response_model=GroupRoundsResponse)
def chat_group_rounds(req: GroupChatRequest):
    """
    2라운드 반응형 그룹 채팅.

    Round 1: 각 캐릭터가 사용자 메시지에 순차 답변
    Round 2: 1라운드 전체 대화를 보고 자율 반응
             — 할 말 없으면 침묵 (해당 캐릭터 응답 제외됨)
    """
    if not 2 <= len(req.characters) <= 5:
        raise HTTPException(status_code=400, detail="캐릭터는 2~5명이어야 합니다.")

    try:
        round_results = run_group_rounds(
            characters=req.characters,
            user_message=req.message,
            history=req.history,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip('"'))

    return GroupRoundsResponse(
        rounds=[
            RoundResponse(
                round=rr.round,
                label=rr.label,
                responses=[
                    ChatResponse(character=r.character, answer=r.answer)
                    for r in rr.responses
                ],
            )
            for rr in round_results
        ]
    )


# ── 그룹 채팅 (인텐트 자동 분류, 영화 추천 포함) ──

@app.post("/chat/group/auto", response_model=GroupAutoRoundsResponse)
def chat_group_auto(req: GroupChatRequest):
    """
    인텐트 자동 분류 후 2라운드 반응형 그룹 채팅.

    영화 추천 인텐트: 영화를 한 번만 검색하고, 각 캐릭터가 같은 목록을
                    자기 톤으로 소개(라운드1) → 서로의 추천에 반응(라운드2).
    캐릭터 대화 인텐트: /chat/group/rounds와 동일하게 동작.
    """
    if not 2 <= len(req.characters) <= 5:
        raise HTTPException(status_code=400, detail="캐릭터는 2~5명이어야 합니다.")

    try:
        intent, movies, round_results = run_group_auto_rounds(
            characters=req.characters,
            user_message=req.message,
            history=req.history,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip('"'))

    return GroupAutoRoundsResponse(
        intent=intent,
        movies=movies,
        rounds=[
            RoundResponse(
                round=rr.round,
                label=rr.label,
                responses=[
                    ChatResponse(character=r.character, answer=r.answer)
                    for r in rr.responses
                ],
            )
            for rr in round_results
        ],
    )


# ── 영화 추천 ──

@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    result = movie_run(
        user_message=req.message,
        character_name=req.character,
        history=req.history,
    )

    return RecommendResponse(
        answer=result.answer,
        movies=result.movies,
    )


# ── 자동 인텐트 분류 라우팅 ──

@app.post("/chat/auto", response_model=AutoResponse)
def chat_auto(req: AutoRequest):
    """
    사용자 입력을 자동으로 분류해서
    영화 추천 또는 캐릭터 대화 파이프라인으로 라우팅.
    """
    intent = classify(req.message)

    if intent == Intent.MOVIE_RECOMMEND:
        result = movie_run(
            user_message=req.message,
            character_name=req.character,
            history=req.history,
        )
        return AutoResponse(
            intent=intent,
            character=result.character,
            answer=result.answer,
            movies=result.movies,
        )
    else:
        if req.character:
            try:
                result = character_run(
                    character_name=req.character,
                    user_message=req.message,
                    history=req.history,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail=f"캐릭터 '{req.character}'를 찾을 수 없습니다.")
        else:
            # 캐릭터 사전 선택 없음 — 메시지에서 캐릭터 언급을 감지해 자동 전환.
            # 언급이 없으면 범용 대화로 응답한다 (character="")
            result = character_auto_run(
                user_message=req.message,
                history=req.history,
            )

        return AutoResponse(
            intent=intent,
            character=result.character,
            answer=result.answer,
        )


# ── 스트리밍 캐릭터 대화 ──

@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """
    캐릭터 대화를 SSE(text/event-stream)로 스트리밍.
    클라이언트는 `data: <token>` 형식으로 토큰을 실시간 수신.
    스트림 종료 시 `data: [DONE]` 전송.
    """
    from cineverse_prompt import build_system_prompt, load_profiles, stream_clean
    from rag.character_retriever import retrieve, format_context
    from llm.client import chat_stream as llm_stream
    from pipeline.character_pipeline import _ANSWER_NOW_REMINDER
    import os

    profile_path = os.environ.get("PROFILE_PATH", "character_profiles_ALL_50.json")
    profiles = load_profiles(profile_path)

    try:
        character_name = resolve_character_names([req.character], profiles)[0]
        system_prompt = build_system_prompt(
            character_name=character_name,
            chat_mode="single",
            profiles=profiles,
            example_count=4,
            compact=True,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"캐릭터 '{req.character}'를 찾을 수 없습니다.")

    messages = [{"role": "system", "content": system_prompt}]

    if req.use_rag:
        try:
            chunks = retrieve(character_name, req.message, top_k=3)
            rag_ctx = format_context(chunks)
            if rag_ctx:
                messages += [
                    {"role": "user", "content": f"[캐릭터 기억]\n{rag_ctx}\n\n위 정보는 캐릭터의 실제 기억이다. 참고하되 캐릭터처럼 자연스럽게 말하라."},
                    {"role": "assistant", "content": "알겠습니다."},
                ]
        except Exception:
            pass

    messages.extend(req.history)
    # 생성 직전에 "지금 실제로 답하라"는 지시를 붙인다. 비스트리밍 run()에 있는 것과
    # 동일한 조치 — 이게 빠져있으면 모델이 실제 사용자 메시지를 예시로 착각하고
    # <start_of_turn>user\n... 형태로 새 턴을 지어내는 빈도가 높아진다.
    messages.append({"role": "user", "content": req.message + _ANSWER_NOW_REMINDER})

    def event_generator():
        sent_any = False
        try:
            for chunk in stream_clean(llm_stream(messages, max_tokens=512)):
                sent_any = True
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            if not sent_any:
                # 특수토큰/thinking 블록만 나오다 끝나서 실제로 보낸 내용이 하나도
                # 없는 경우 — 빈 응답 대신 안전한 대체 문구를 보낸다.
                yield f"data: {json.dumps('...', ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")