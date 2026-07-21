import os
import re
from dataclasses import dataclass, field
from cineverse_prompt import build_system_prompt, clean_and_truncate, truncate_to_sentences, load_profiles
from rag.movie_retriever import MovieFilter, retrieve, format_for_prompt, to_response
from pipeline.query_rewriter import rewrite
from llm.client import chat

# 이유 없이 막연히 부정적인 반응만 (짧은 리액션 위주). 길게 이유를 덧붙이면 아래 정규식엔 걸려도
# _is_vague_negative의 길이 컷으로 걸러진다.
_VAGUE_NEGATIVE = re.compile(
    r"별로|끌리는\s*게\s*없|당기는\s*게\s*없|마음에\s*안\s*들|재미없어\s*보여|안\s*땡겨|그닥|와닿지\s*않"
)


def _is_vague_negative(message: str) -> bool:
    """구체적인 이유 없이 짧게 부정 반응만 보인 경우 True."""
    if not _VAGUE_NEGATIVE.search(message):
        return False
    return len(message.strip()) <= 20

_BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.environ.get("PROFILE_PATH", os.path.join(_BASE_DIR, "character_profiles_ALL_50.json"))
_profiles = None

def get_profiles():
    global _profiles
    if _profiles is None:
        _profiles = load_profiles(PROFILE_PATH)
    return _profiles

@dataclass
class MovieRecommendResult:
    answer: str
    movies: list = field(default_factory=list)
    search_query: str = ""
    filters_used: dict = field(default_factory=dict)
    character: str = ""  # 별칭이 들어왔으면 정식 이름으로 변환된 값 (없으면 "")

def run(user_message, character_name=None, history=None, top_k=3, max_tokens=1024):
    if history is None:
        history = []
    if character_name:
        from pipeline.character_pipeline import resolve_character_names
        try:
            character_name = resolve_character_names([character_name], get_profiles())[0]
        except KeyError:
            # 모르는 캐릭터명이면 캐릭터 없는 일반 추천으로 조용히 폴백
            # (영화 추천은 캐릭터가 필수가 아니라서 404보다 이 편이 더 안전함)
            character_name = None
    rewritten = rewrite(user_message)
    search_q = rewritten.get("search_query", user_message)
    filters = MovieFilter(
        genre=rewritten.get("genre"), actor=rewritten.get("actor"),
        director=rewritten.get("director"), language=rewritten.get("language"),
        year_from=rewritten.get("year_from"), year_to=rewritten.get("year_to"),
        min_rating=rewritten.get("min_rating"),
    )
    print(f"  [MoviePipeline] search_query='{search_q}' filters={filters}")
    movies = retrieve(search_q, top_k=top_k, movie_filter=filters)
    if not movies:
        movies = retrieve(search_q, top_k=top_k)
    movie_context = format_for_prompt(movies)
    movie_titles  = ", ".join(f"'{m['title']}'" for m in movies)
    profiles = get_profiles()
    feedback_rule = (
        "\n\n[추천 영화 제한 — 반드시 지킬 것]\n"
        f"- 지금 추천할 수 있는 영화는 오직 아래 [추천 영화 목록]에 있는 것뿐이다: {movie_titles}\n"
        "- 이 목록에 없는 영화 제목은 절대 언급하지 마라. 아는 영화라도 목록에 없으면 추천하지 않는다.\n"
        "- 목록에 사용자 요청에 맞는 영화가 없으면, 없다고 솔직히 말하고 목록 중 그나마 가까운 것을 대안으로 제시한다.\n"
        "\n[추천 후 규칙]\n"
        "- 영화를 추천할 때는 왜 이 영화들을 골랐는지 간단히 설명한다.\n"
        "- 추천 답변 끝에는 '이 중에 끌리는 거 있어?' 같은 식으로 사용자 반응을 가볍게 물어본다.\n"
        "- 사용자가 이유를 대며 부정적으로 반응하면(예: 장르가 싫다, 너무 무겁다, 잔인한 게 싫다) "
        "그 이유에 맞춰 위 [추천 영화 목록] 중에서만 골라 다시 제안한다."
    )

    if character_name:
        try:
            system_prompt = build_system_prompt(character_name=character_name, chat_mode="single", profiles=profiles, example_count=4, compact=True, movie_mode=True)
            system_prompt += "\n\n너는 캐릭터로서 아래 영화들을 참고해서 추천한다. 캐릭터 말투를 유지하되 영화 정보는 정확하게 전달한다."
        except KeyError:
            system_prompt = "당신은 영화 추천 전문가입니다."
    else:
        system_prompt = (
            "당신은 CineVerse의 영화 추천 어시스턴트다. 사용자와 실시간으로 대화하며 "
            "아래 영화 목록을 참고해서 추천 답변을 직접 작성한다.\n"
            "마크다운 헤더·볼드·번호 목록 없이 자연스러운 한국어 문장으로만 답하세요."
        )

    system_prompt += feedback_rule
    messages = [{"role": "system", "content": system_prompt}]
    if movie_context:
        messages += [
            {"role": "user", "content": f"[추천 영화 목록]\n{movie_context}\n\n위 영화들을 참고해서 답변해줘."},
            {"role": "assistant", "content": "알겠습니다."},
        ]
    messages.extend(history)

    # 마지막 유저 메시지에 "지금 실제로 답하라"는 지시를 직접 붙인다.
    # (시스템 프롬프트 앞부분에 넣으면 뒤이은 "추천 목록 참고해줘/알겠습니다" 가짜 대화에
    #  프라이밍되어, 모델이 실제 사용자 메시지를 새로운 예시 질문으로 착각하고
    #  <start_of_turn>user\n(사용자 질문을 재구성한 문장) 형태로 답변 대신 질문을
    #  또 만들어내는 경우가 있다. 생성 직전 위치에 둬야 실제로 지켜짐)
    reminder = (
        "\n\n[지금 이 메시지에 바로 답변해라]\n"
        "너는 지금 어시스턴트로서 위 사용자 메시지에 답할 차례다. "
        "사용자인 척 다른 질문을 만들어내지 말고, 대화를 이어가려 하지 말고, "
        "오직 이 메시지에 대한 실제 추천 답변만 출력해라."
    )

    if _is_vague_negative(user_message):
        final_user_content = (
            f"{user_message}\n\n"
            "[이번 답변 전용 지시 — 반드시 따를 것]\n"
            "위 반응은 구체적인 이유 없는 막연한 부정 반응이다. "
            "이번 답변에서는 영화 제목을 단 하나도 언급하지 마라. "
            "오직 어떤 점이 별로였는지 묻는 질문 한 문장만 출력해라."
        )
    else:
        final_user_content = user_message + reminder

    messages.append({"role": "user", "content": final_user_content})
    raw = chat(messages, max_tokens=max_tokens)
    if character_name:
        answer = clean_and_truncate(raw, character_name)
    else:
        # 캐릭터 없는 추천: 마크다운 정제 후 4문장으로 제한
        from cineverse_prompt import clean_llm_output
        answer = truncate_to_sentences(clean_llm_output(raw), max_sentences=4)
    if not answer:
        answer = "죄송합니다. 추천 결과를 생성하지 못했습니다."
    return MovieRecommendResult(
        answer=answer, movies=to_response(movies),
        search_query=search_q,
        filters_used={k: v for k, v in rewritten.items() if k != "search_query" and v},
        character=character_name or "",
    )
