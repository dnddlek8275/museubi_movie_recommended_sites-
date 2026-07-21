import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from cineverse_prompt import build_system_prompt, clean_and_truncate, load_profiles
from rag.character_retriever import retrieve, format_context
from llm.client import chat

_BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.environ.get("PROFILE_PATH", os.path.join(_BASE_DIR, "character_profiles_ALL_50.json"))
_profiles = None

def get_profiles():
    global _profiles
    if _profiles is None:
        _profiles = load_profiles(PROFILE_PATH)
    return _profiles

# 프로필 정식 이름과 다르게 흔히 불리는 별칭 매핑 (별칭 → 정식 이름)
CHARACTER_ALIASES = {
    "아이언맨":     "토니 스타크",
    "아이언 맨":    "토니 스타크",
    "캡틴 아메리카": "스티브 로저스",
    "캡틴":        "스티브 로저스",
    "스파이더맨":   "피터 파커",
    "스파이더 맨":  "피터 파커",
    "스트레인지":   "닥터 스트레인지",
    "헐크":        "브루스 배너",
    "배트맨":      "브루스 웨인",
    "클라크 켄트":  "슈퍼맨",
    "클락 켄트":    "슈퍼맨",
    "다이애나":     "원더우먼",
    "스네이프":     "세베루스 스네이프",
    "덤블도어":     "알버스 덤블도어",
}


# 대표성이 아주 강한 아이템/능력만 우선 등록 (전체 50인 전수 작업은 아님).
# 그룹챗에서 "질문 주제가 특정 캐릭터의 시그니처 능력과 강하게 엮여있으면
# 다른 캐릭터도 그걸 자기 것처럼 말한다"는 문제가 실측으로 확인돼서,
# 프롬프트 지시만으론 못 막아 생성 후 코드로 한 번 더 거른다.
CHARACTER_SIGNATURE_ITEMS = {
    "토니 스타크":    ["아크 리액터", "나노 슈트"],
    "스티브 로저스":  ["방패를 던지", "비브라늄 방패"],
    "피터 파커":      ["웹슈터", "웹 슈터", "웹 플라", "거미줄"],
    "토르":          ["묠니르"],
    "브루스 웨인":    ["배트모빌", "배트랑", "배트슈트"],
    "원더우먼":       ["황금 올가미", "라쏘"],
    "프로도":        ["절대반지"],
    "간달프":        ["글람드링"],
    "알버스 덤블도어": ["엘더완드"],
}


def _strip_identity_bleed(answer: str, character: str) -> str:
    """
    다른 캐릭터의 대표 아이템/능력을 자기 것처럼 말하는 문장을 제거한다.
    (예: 해리포터가 스파이더맨의 "웹슈터"를 자기 것처럼 언급) 문장 전체가 걸리면
    빈 답변보다는 원문을 그대로 둔다 (safety_filter와 같은 방침).
    """
    other_items = [
        item for owner, items in CHARACTER_SIGNATURE_ITEMS.items()
        if owner != character
        for item in items
    ]
    if not other_items or not answer:
        return answer

    sentences = [s for s in re.split(r"(?<=[.!?。！？])\s+|\n", answer) if s.strip()]
    kept = [s for s in sentences if not any(item in s for item in other_items)]

    if not kept or len(kept) == len(sentences):
        return answer
    return " ".join(kept).strip()


def _strip_name_claim_bleed(answer: str, character: str, profiles: dict) -> str:
    """
    "내 아이언맨 슈트", "제 스파이더맨 능력"처럼 다른 캐릭터의 이름(정식 이름 또는
    별칭)을 자기 소유물인 것처럼 언급하는 문장을 제거한다.

    CHARACTER_SIGNATURE_ITEMS는 미리 등록해둔 아이템만 잡지만, 이건 50인 명단 +
    별칭 전체를 대상으로 해서 훨씬 넓게 잡는다 (예: "아이언맨 슈트"처럼 목록에
    없던 표현도 "아이언맨"이라는 이름 자체가 걸려서 잡힘).
    """
    if not answer:
        return answer

    canonical_self = CHARACTER_ALIASES.get(character, character)
    all_names = set(profiles["characters"].keys()) | set(CHARACTER_ALIASES.keys())
    other_names = sorted(
        (n for n in all_names if CHARACTER_ALIASES.get(n, n) != canonical_self),
        key=len, reverse=True,
    )
    if not other_names:
        return answer

    # "내"/"제" 뒤에 다른 캐릭터 이름이 오고, 그 뒤가 조사·공백·문장부호·끝으로
    # 이어질 때만 매칭한다 (예: "네오클래식" 같은 무관한 단어까지 걸리는 걸 방지).
    alt = "|".join(re.escape(n) for n in other_names)
    pattern = re.compile(
        r"(?:내|제)\s*(?:" + alt + r")(?=[\s.,!?~을를이가는의와과]|$)"
    )

    sentences = [s for s in re.split(r"(?<=[.!?。！？])\s+|\n", answer) if s.strip()]
    kept = [s for s in sentences if not pattern.search(s)]

    if not kept or len(kept) == len(sentences):
        return answer
    return " ".join(kept).strip()


_QUOTED = re.compile(r"['‘’\"“”]([^'‘’\"“”]{1,30})['‘’\"“”]")


def _strip_unlisted_movie_quotes(answer: str, movie_titles: str) -> str:
    """
    영화 추천 반응(2라운드)에서 따옴표로 감싼 영화 제목이 실제 검색된 목록에
    없으면 그 문장을 제거한다. (1라운드 추천은 재시도+폴백으로 이미 막았지만,
    2라운드 반응은 프롬프트 제약만 있어서 가끔 목록 밖 영화를 "따옴표로 인용해
    새로 추천"하는 경우가 있다 — 코드로 한 번 더 거른다)
    """
    if not movie_titles or not answer:
        return answer

    quoted = _QUOTED.findall(answer)
    unlisted = [q for q in quoted if q not in movie_titles]
    if not unlisted:
        return answer

    sentences = [s for s in re.split(r"(?<=[.!?。！？])\s+|\n", answer) if s.strip()]
    kept = [s for s in sentences if not any(u in s for u in unlisted)]

    if not kept or len(kept) == len(sentences):
        return answer
    return " ".join(kept).strip()


def resolve_character_names(characters: list[str], profiles: dict) -> list[str]:
    """
    그룹 채팅용 캐릭터 이름 목록을 정규화한다.
    별칭("아이언맨" 등)은 정식 이름으로 바꾸고, 그래도 50인 명단에 없으면
    KeyError를 던진다 (main.py에서 잡아서 404로 변환).

    /chat/auto의 자유 대화 경로(detect_character)는 메시지에서 캐릭터를 "찾아내는"
    용도였다면, 이건 그룹 채팅처럼 캐릭터가 이미 정해져서 넘어온 경우 별칭만
    정규화하는 용도라 별개 함수로 둔다.
    """
    resolved = []
    unknown = []
    for name in characters:
        canonical = CHARACTER_ALIASES.get(name, name)
        if canonical in profiles["characters"]:
            resolved.append(canonical)
        else:
            unknown.append(name)
    if unknown:
        raise KeyError(f"캐릭터를 찾을 수 없습니다: {', '.join(unknown)}")
    return resolved


def detect_character(user_message: str, profiles: dict) -> str | None:
    """
    메시지 안에 50인 캐릭터 명단 중 이름(또는 별칭)이 언급됐는지 확인.
    가장 긴 이름부터 검사해서 부분 문자열 충돌을 피한다.

    캐릭터 사전 선택 없이 자유 대화하다가 "마석도랑 얘기하고 싶어"처럼
    특정 캐릭터를 언급하면 그 캐릭터로 전환하는 데 쓴다.
    (인텐트가 이미 character_chat으로 분류된 상태에서만 호출되므로,
     이름이 나오면 영화 얘기가 아니라 그 캐릭터와 대화하려는 의도로 본다.)
    """
    candidates = list(profiles["characters"].keys()) + list(CHARACTER_ALIASES.keys())
    candidates.sort(key=len, reverse=True)

    for name in candidates:
        if name in user_message:
            return CHARACTER_ALIASES.get(name, name)
    return None


# "OOO랑 얘기하고 싶어", "OOO 불러줘"처럼 캐릭터를 요청하는 문구 패턴.
# 이 패턴에는 걸리는데 50인 명단에 없으면 "미지원 캐릭터"로 판단한다.
_CHARACTER_TRIGGER_PATTERNS = [
    re.compile(r"([가-힣A-Za-z0-9]{2,12})\s*(?:이랑|랑|하고|와|과)\s*(?:얘기|대화|말|채팅)"),
    re.compile(r"([가-힣A-Za-z0-9]{2,12})\s*(?:불러|나와)\s*(?:줘|줄래|주라|봐)?"),
]


def detect_character_request(user_message: str, profiles: dict) -> tuple[str | None, bool]:
    """
    메시지에서 캐릭터 언급/요청을 감지.

    Returns:
        (character_name, is_unsupported)
        - 50인 명단 안에 있으면 (이름, False)
        - 캐릭터를 불러달라는 문구는 있는데 명단에 없으면 (None, True)
        - 그런 문구도 없으면 (None, False) — 그냥 일반 대화
    """
    matched = detect_character(user_message, profiles)
    if matched:
        return matched, False

    for pattern in _CHARACTER_TRIGGER_PATTERNS:
        if pattern.search(user_message):
            return None, True

    return None, False


def _is_echo(answer: str, user_message: str) -> bool:
    """
    생성된 답변이 실제 답 대신 사용자 메시지를 그대로 되풀이한 것인지 감지한다.
    (공백/문장부호 제거 후 완전히 같거나, 답변이 사용자 메시지를 통째로 포함하면서
     별로 안 길면 "답변인 척한 질문 반복"으로 본다)
    """
    norm = lambda s: re.sub(r"[\s?!.,~♡ㅋㅎ]+", "", s)
    a, u = norm(answer), norm(user_message)
    if not a or not u:
        return False
    return a == u or (len(u) >= 6 and u in a and len(a) <= len(u) * 1.3)


# 생성 직전(마지막 유저 메시지)에 붙이는 지시. 시스템 프롬프트 앞부분에만 넣으면,
# 모델이 실제 사용자 메시지를 예시 질문으로 착각하고 답변 대신
# <start_of_turn>user\n(질문을 재구성한 문장)을 내는 경우가 있어 이를 방지한다.
_ANSWER_NOW_REMINDER = (
    "\n\n[지금 이 메시지에 바로 답변해라]\n"
    "너는 지금 어시스턴트로서 위 사용자 메시지에 답할 차례다. "
    "사용자인 척 다른 질문을 만들어내지 말고, 대화를 이어가려 하지 말고, "
    "오직 이 메시지에 대한 실제 답변만 출력해라."
)


GENERAL_CHAT_SYSTEM_PROMPT = """너는 CineVerse의 범용 대화 어시스턴트다.
특정 영화 캐릭터가 아니라 너 자신으로서 자연스럽고 편하게 대화한다.
- 1~3문장으로 답한다.
- 마크다운, 이름 접두어, 특수토큰 없이 대사만 출력한다.
- 사용자가 특정 캐릭터 이름을 언급하면 그 캐릭터로 전환해서 대화할 수 있다는 걸 알고 있다.
- '힘내', '포기하지 마', '너 자신을 믿어', '함께라면 이겨낼 수 있어요', '우리는 늘 곁에 있어요',
  '진정한 나를 찾아', '내면의 목소리' 같은 상담사·자기계발서 투 문구를 쓰지 마라.
  대신 친구처럼 담백하고 구체적으로 반응해라."""


@dataclass
class CharacterChatResult:
    character: str
    answer: str
    finish_reason: str = "stop"
    rag_used: bool = False


@dataclass
class RoundResult:
    round: int
    label: str
    responses: list = field(default_factory=list)  # list[CharacterChatResult]


# 침묵 판정 — LLM이 이 텍스트를 출력하면 "할 말 없음"으로 처리
_SILENCE_TOKENS = {"(침묵)", "침묵", "...", "（침묵）", "(silence)"}

def _build_round1_context(round1: list[CharacterChatResult]) -> str:
    """1라운드 답변을 대화 맥락 텍스트로 변환."""
    return "\n".join(f"[{r.character}]: {r.answer}" for r in round1)


def _get_reaction(
    character: str,
    profiles: dict,
    characters: list[str],
    user_message: str,
    round1: list[CharacterChatResult],
    max_tokens: int = 256,
    movie_titles: str | None = None,
) -> str | None:
    """
    캐릭터가 1라운드 대화를 보고 반응할지 판단 후 답변 반환.
    침묵이면 None 반환.

    movie_titles가 주어지면(영화 추천 라운드에 대한 반응인 경우) 실제 검색된
    영화 목록 밖의 영화를 새로 지어내 언급하지 못하도록 제약을 건다.
    """
    try:
        system_prompt = build_system_prompt(
            character_name=character,
            chat_mode="multi",
            profiles=profiles,
            other_characters=characters,
            example_count=4,
            compact=True,
        )
    except KeyError:
        return None

    # 이 캐릭터 본인 발언과 다른 캐릭터 발언을 분리
    my_answer   = next((r.answer for r in round1 if r.character == character), None)
    others      = [r for r in round1 if r.character != character]
    others_text = "\n".join(f"[{r.character}]: {r.answer}" for r in others)

    reaction_prompt = (
        f"[사용자 메시지]\n{user_message}\n\n"
        f"[방금 대화방에서 나온 말들]\n{others_text}\n\n"
    )
    if my_answer:
        reaction_prompt += f"[네가 방금 한 말]\n{my_answer}\n\n"

    if movie_titles:
        reaction_prompt += (
            f"[주의] 지금 대화 주제는 영화 추천이다. 언급 가능한 영화는 오직 {movie_titles}뿐이다. "
            "이 목록에 없는 다른 영화 제목을 새로 지어내 언급하지 마라.\n\n"
        )

    reaction_prompt += (
        f"너는 [{character}]다. 위 대화를 보고 반응해라.\n"
        "규칙:\n"
        "- 다른 캐릭터 말에 직접 동의·반박·딴지 중 하나를 1~2문장으로 해라.\n"
        "- 이름을 불러도 된다. 예: '장첸 말은 틀렸어', '토르 말이 맞긴 한데...'\n"
        "- 네가 방금 한 말이나 같은 뜻을 반복하지 마라.\n"
        "- 딱히 할 말이 없으면 (침묵) 만 출력해라."
        + _ANSWER_NOW_REMINDER
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": reaction_prompt},
    ]

    raw    = chat(messages, max_tokens=max_tokens)
    answer = clean_and_truncate(raw, character)

    if answer and _is_echo(answer, user_message):
        raw    = chat(messages, max_tokens=max_tokens)
        answer = clean_and_truncate(raw, character)

    if answer:
        answer = _strip_identity_bleed(answer, character)
        answer = _strip_name_claim_bleed(answer, character, profiles)
        if movie_titles:
            answer = _strip_unlisted_movie_quotes(answer, movie_titles)

    if not answer or answer.strip() in _SILENCE_TOKENS:
        return None
    return answer


def _run_character_round1(
    characters: list[str],
    user_message: str,
    history: list[dict],
    profiles: dict,
    max_tokens: int,
) -> list[CharacterChatResult]:
    """캐릭터 대화 1라운드: 각 캐릭터가 순차로 답변 (이전 캐릭터 발언 포함)."""
    r1_results: list[CharacterChatResult] = []
    running_history = list(history)

    for character in characters:
        try:
            system_prompt = build_system_prompt(
                character_name=character,
                chat_mode="multi",
                profiles=profiles,
                other_characters=characters,
                example_count=4,
                compact=True,
            )
        except KeyError:
            continue

        messages = [{"role": "system", "content": system_prompt}]

        try:
            chunks = retrieve(character, user_message, top_k=2)
            rag_ctx = format_context(chunks)
            if rag_ctx:
                messages += [
                    {"role": "user",      "content": f"[캐릭터 기억]\n{rag_ctx}\n\n위 정보는 캐릭터의 실제 기억이다. 참고하되 캐릭터처럼 자연스럽게 말하라."},
                    {"role": "assistant", "content": "알겠습니다."},
                ]
        except Exception:
            pass

        messages.extend(running_history)
        # 생성 직전에 "지금 실제로 답하라"는 지시를 붙인다. RAG 기억 주입이나 이전
        # 캐릭터 발언 때문에 대화가 길어지면, 모델이 실제 사용자 메시지를 예시로
        # 착각하고 답변 대신 새 질문을 지어내는 경우가 있어 이를 방지한다.
        messages.append({"role": "user", "content": user_message + _ANSWER_NOW_REMINDER})

        raw    = chat(messages, max_tokens=max_tokens)
        answer = clean_and_truncate(raw, character) or "..."

        # 답변이 사용자 메시지를 그대로 되풀이한 경우(패턴 이어쓰기 실패) 한 번 재시도.
        # 그래도 실패하면 캐릭터 색은 없지만 최소한 자연스러운 문장으로 대체한다.
        if _is_echo(answer, user_message):
            raw    = chat(messages, max_tokens=max_tokens)
            answer = clean_and_truncate(raw, character) or "..."
            if _is_echo(answer, user_message):
                answer = "음, 잠깐 생각 좀 해볼게."

        answer = _strip_identity_bleed(answer, character)
        answer = _strip_name_claim_bleed(answer, character, profiles)

        r1_results.append(CharacterChatResult(character=character, answer=answer))
        running_history.append({"role": "user",      "content": user_message})
        running_history.append({"role": "assistant", "content": f"[{character}]: {answer}"})

    return r1_results


def _run_movie_pitch_round(
    characters: list[str],
    user_message: str,
    profiles: dict,
    max_tokens: int,
) -> tuple[list[dict], list[CharacterChatResult], str]:
    """
    영화 추천 1라운드: 참여 캐릭터 중 한 명을 무작위로 골라 그 캐릭터가 추천한다.
    (전원이 각자 추천하면 후보가 3개뿐이라 서로 겹치기 쉽고, 매번 "질문을 되풀이하며
     답을 안 하는" 실패가 인원수만큼 반복될 위험도 커진다. 한 명만 확실히 추천하게 하고
     나머지는 2라운드에서 그 추천에 대한 의견을 내는 편이 더 자연스럽고 안정적이다.)

    Returns:
        (movies, [단일 CharacterChatResult], movie_titles)
        movie_titles는 2라운드 반응에서 "목록 밖 영화 언급 금지" 제약을 걸 때 재사용한다.
    """
    from pipeline.query_rewriter import rewrite as rewrite_query
    from rag.movie_retriever import MovieFilter, retrieve as movie_retrieve, format_for_prompt, to_response

    rewritten = rewrite_query(user_message)
    search_q  = rewritten.get("search_query", user_message)
    filters   = MovieFilter(
        genre=rewritten.get("genre"), actor=rewritten.get("actor"),
        director=rewritten.get("director"), language=rewritten.get("language"),
        year_from=rewritten.get("year_from"), year_to=rewritten.get("year_to"),
        min_rating=rewritten.get("min_rating"),
    )
    movies = movie_retrieve(search_q, top_k=3, movie_filter=filters)
    if not movies:
        movies = movie_retrieve(search_q, top_k=3)

    movie_context = format_for_prompt(movies)
    movie_titles  = ", ".join(f"'{m['title']}'" for m in movies)

    # 제약 문구는 시스템 프롬프트에, 실제 영화 목록 본문은 별도의 가짜
    # user/assistant 확인 대화로 넣는다. (movie_pipeline.py의 1:1 추천에서
    # 검증된 구조 — 목록을 시스템 프롬프트에 통째로 욱여넣으면 오히려
    # 목록 밖 영화를 지어내는 빈도가 높아지는 게 실측으로 확인됐다)
    movie_rule = (
        "\n\n[영화 추천 제한 — 반드시 지킬 것]\n"
        f"- 지금 추천할 수 있는 영화는 오직 아래 [추천 영화 목록]에 있는 것뿐이다: {movie_titles}\n"
        "- 이 목록에 없는 영화 제목은 절대 언급하지 마라. 아는 영화라도 목록에 없으면 추천하지 않는다.\n"
        "- 위 영화 중 네 캐릭터라면 어떤 걸 왜 추천할지 네 말투로 짧게 소개해라."
    )

    # 생성 직전(마지막 유저 메시지)에 "지금 실제로 답하라"는 지시를 붙인다.
    # 시스템 프롬프트 앞부분에만 넣으면, 모델이 실제 사용자 메시지를 예시 질문으로
    # 착각하고 답변 대신 <start_of_turn>user\n(질문을 재구성한 문장)을 내는 경우가 있다.
    reminder = (
        "\n\n[지금 이 메시지에 바로 답변해라]\n"
        "너는 지금 어시스턴트로서 위 사용자 메시지에 답할 차례다. "
        "사용자인 척 다른 질문을 만들어내지 말고, 오직 이 메시지에 대한 실제 추천 답변만 출력해라."
    )

    chosen = random.choice(characters)

    try:
        system_prompt = build_system_prompt(
            character_name=chosen,
            chat_mode="multi",
            profiles=profiles,
            other_characters=characters,
            example_count=4,
            compact=True,
            movie_mode=True,
        )
    except KeyError:
        system_prompt = "당신은 영화 추천 전문가입니다."

    system_prompt += movie_rule

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"[추천 영화 목록]\n{movie_context}\n\n위 영화들을 참고해서 답변해줘."},
        {"role": "assistant", "content": "알겠습니다."},
        {"role": "user", "content": user_message + reminder},
    ]

    raw    = chat(messages, max_tokens=max_tokens)
    answer = clean_and_truncate(raw, chosen) or "..."

    # 프롬프트 제약만으로는 목록 밖 영화를 지어내는 경우가 실측으로 확인돼서
    # 코드 레벨로 한 번 더 검증한다.
    # 1) 따옴표로 인용된 목록 밖 영화 제목이 있으면 그 문장부터 제거한다.
    #    (실제 목록 제목이 "사랑 이야기"처럼 흔한 관용구와 겹치면, 그 구절이
    #     문장 어딘가에 우연히 섞여 있다는 이유만으로 "정상 제목 포함"으로
    #     오판하고 넘어가는 경우가 있어 — 인용부호 검증을 먼저 한다)
    # 2) 그래도 실제 목록 제목이 하나도 안 남으면 재시도, 최종 실패 시 안전 폴백.
    actual_titles = [m["title"] for m in movies]
    if actual_titles:
        answer = _strip_unlisted_movie_quotes(answer, movie_titles)
        if not any(t in answer for t in actual_titles):
            raw    = chat(messages, max_tokens=max_tokens)
            answer = clean_and_truncate(raw, chosen) or "..."
            answer = _strip_unlisted_movie_quotes(answer, movie_titles)
            if not any(t in answer for t in actual_titles):
                answer = f"'{actual_titles[0]}' 어때? 딱 네 취향일 것 같은데."

    answer = _strip_name_claim_bleed(answer, chosen, profiles)

    r1_results = [CharacterChatResult(character=chosen, answer=answer)]
    return to_response(movies), r1_results, movie_titles


def _run_reaction_round(
    characters: list[str],
    user_message: str,
    profiles: dict,
    r1_results: list[CharacterChatResult],
    max_tokens: int,
    movie_titles: str | None = None,
) -> list[CharacterChatResult]:
    """
    1라운드 결과를 보고 각 캐릭터가 자율적으로 반응 (침묵 가능).

    각 캐릭터의 반응은 r1_results(고정)만 보고 만들어서 서로 독립적이므로 병렬 호출한다.
    (llama-server가 --skip-chat-parsing으로 동시 슬롯 문법 검증 레이스 버그를 우회하고
     np=5로 그룹챗 최대 인원까지 동시 처리를 지원하도록 설정돼 있어야 함)

    movie_titles가 주어지면(영화 추천에 대한 반응인 경우) 목록 밖 영화를
    지어내 언급하지 못하도록 각 반응 생성에 제약을 건다.
    """
    with ThreadPoolExecutor(max_workers=len(characters)) as executor:
        futures = {
            executor.submit(
                _get_reaction,
                character=character,
                profiles=profiles,
                characters=characters,
                user_message=user_message,
                round1=r1_results,
                max_tokens=max_tokens,
                movie_titles=movie_titles,
            ): character
            for character in characters
        }
        reactions = {futures[f]: f.result() for f in futures}

    r2_results: list[CharacterChatResult] = []
    for character in characters:
        reaction = reactions.get(character)
        if reaction:
            r2_results.append(CharacterChatResult(character=character, answer=reaction))
    return r2_results


def run_group_rounds(
    characters: list[str],
    user_message: str,
    history: list[dict] | None = None,
    max_tokens_r1: int = 512,
    max_tokens_r2: int = 256,
) -> list[RoundResult]:
    """
    2라운드 그룹 채팅 (캐릭터 대화 전용 — 영화 추천은 run_group_auto_rounds 참고).

    Round 1: 각 캐릭터가 user 메시지에 순차 답변 (이전 캐릭터 발언 포함)
    Round 2: 1라운드 전체 대화를 보고 각 캐릭터가 자율적으로 반응
             — 할 말 없으면 침묵 (응답 목록에서 제외)

    Returns:
        [RoundResult(round=1, ...), RoundResult(round=2, ...)]
        round 2 responses는 반응한 캐릭터만 포함 (0개일 수도 있음)
    """
    if history is None:
        history = []

    profiles = get_profiles()
    characters = resolve_character_names(characters, profiles)

    r1_results = _run_character_round1(characters, user_message, history, profiles, max_tokens_r1)
    r2_results = _run_reaction_round(characters, user_message, profiles, r1_results, max_tokens_r2)

    return [
        RoundResult(round=1, label="첫 번째 답변", responses=r1_results),
        RoundResult(round=2, label="반응",          responses=r2_results),
    ]


def run_group_auto_rounds(
    characters: list[str],
    user_message: str,
    history: list[dict] | None = None,
    max_tokens_r1: int = 512,
    max_tokens_r2: int = 256,
) -> tuple[str, list[dict], list[RoundResult]]:
    """
    인텐트 자동 분류 후 2라운드 그룹 채팅.

    영화 추천 인텐트: 영화를 한 번만 검색하고, 각 캐릭터가 같은 목록을
                    자기 톤으로 소개(라운드1) → 서로의 추천에 반응(라운드2).
    캐릭터 대화 인텐트: run_group_rounds()와 동일하게 동작.

    Returns:
        (intent, movies, [RoundResult(round=1,...), RoundResult(round=2,...)])
    """
    from pipeline.intent import classify, Intent

    if history is None:
        history = []

    profiles = get_profiles()
    characters = resolve_character_names(characters, profiles)
    intent = classify(user_message)

    movie_titles = None
    if intent == Intent.MOVIE_RECOMMEND:
        movies, r1_results, movie_titles = _run_movie_pitch_round(characters, user_message, profiles, max_tokens_r1)
    else:
        movies = []
        r1_results = _run_character_round1(characters, user_message, history, profiles, max_tokens_r1)

    r2_results = _run_reaction_round(
        characters, user_message, profiles, r1_results, max_tokens_r2, movie_titles=movie_titles,
    )

    rounds = [
        RoundResult(round=1, label="첫 번째 답변", responses=r1_results),
        RoundResult(round=2, label="반응",          responses=r2_results),
    ]
    return intent, movies, rounds

def run(character_name, user_message, history=None, use_rag=True, max_tokens=512):
    if history is None:
        history = []
    profiles = get_profiles()
    character_name = resolve_character_names([character_name], profiles)[0]
    system_prompt = build_system_prompt(character_name=character_name, chat_mode="single", profiles=profiles, example_count=4, compact=True)
    rag_used = False
    rag_context = ""
    if use_rag:
        try:
            chunks = retrieve(character_name, user_message, top_k=3)
            rag_context = format_context(chunks)
            rag_used = bool(rag_context)
        except Exception as e:
            print(f"  [CharacterPipeline] RAG 에러 (무시): {e}")
    messages = [{"role": "system", "content": system_prompt}]
    if rag_context:
        messages += [
            {"role": "user", "content": f"[캐릭터 기억]\n{rag_context}\n\n위 정보는 캐릭터의 실제 기억이다. 참고하되 캐릭터처럼 자연스럽게 말하라."},
            {"role": "assistant", "content": "알겠습니다."},
        ]
    messages.extend(history)
    # 생성 직전에 "지금 실제로 답하라"는 지시를 붙인다. RAG 기억 주입 때문에 대화가
    # 길어지면, 모델이 실제 사용자 메시지를 예시로 착각하고 답변 대신 새 질문을
    # 지어내는 경우가 있어 이를 방지한다. (그룹챗에서 먼저 발견/수정한 것과 동일 패턴)
    messages.append({"role": "user", "content": user_message + _ANSWER_NOW_REMINDER})
    raw = chat(messages, max_tokens=max_tokens)
    answer = clean_and_truncate(raw, character_name)

    # 답변이 사용자 메시지를 그대로 되풀이한 경우(패턴 이어쓰기 실패) 한 번 재시도.
    if answer and _is_echo(answer, user_message):
        raw    = chat(messages, max_tokens=max_tokens)
        answer = clean_and_truncate(raw, character_name)

    if answer:
        answer = _strip_identity_bleed(answer, character_name)
        answer = _strip_name_claim_bleed(answer, character_name, profiles)

    if not answer:
        answer = "..."
    return CharacterChatResult(character=character_name, answer=answer, rag_used=rag_used)


def run_auto(user_message, history=None, use_rag=True, max_tokens=512):
    """
    캐릭터 사전 선택 없는 자유 대화.

    메시지에서 50인 명단 중 캐릭터가 언급되면 그 캐릭터로 전환해서 답한다.
    캐릭터를 불러달라는 문구는 있는데 명단에 없으면 미지원 안내 + 랜덤 3명 추천.
    아무 언급도 없으면 범용 어시스턴트로 답한다.

    Returns:
        CharacterChatResult(character="캐릭터명" 또는 "", answer=..., rag_used=...)
        character가 빈 문자열이면 특정 캐릭터로 고정된 게 아니라는 뜻 — 이후 턴에서
        프론트/백엔드가 굳이 캐릭터를 고정할 필요 없다는 신호로 쓸 수 있다.
    """
    if history is None:
        history = []
    profiles = get_profiles()

    character_name, unsupported = detect_character_request(user_message, profiles)

    if character_name:
        return run(character_name, user_message, history=history, use_rag=use_rag, max_tokens=max_tokens)

    if unsupported:
        suggestions = random.sample(list(profiles["characters"].keys()), 3)
        answer = (
            "앗, 해당 캐릭터는 아직 업데이트 전입니다. "
            f"대신 이 친구들은 어때요? {', '.join(suggestions)}"
        )
        return CharacterChatResult(character="", answer=answer, rag_used=False)

    messages = [{"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    raw = chat(messages, max_tokens=max_tokens)
    answer = clean_and_truncate(raw, "") or "..."
    return CharacterChatResult(character="", answer=answer, rag_used=False)


def run_group(characters, user_message, history=None, max_tokens=512):
    """
    단순 그룹 채팅 (반응 라운드 없음).

    _run_character_round1()과 완전히 같은 로직이라 중복 구현하지 않고 그대로 재사용한다.
    (예전엔 이 함수가 별도로 구현돼 있어서, _run_character_round1에 낸 수정이
     여기엔 반영 안 되는 문제가 있었다 — 같은 코드를 두 번 유지하지 않도록 통합함)
    """
    if history is None:
        history = []
    profiles = get_profiles()
    characters = resolve_character_names(characters, profiles)
    return _run_character_round1(characters, user_message, history, profiles, max_tokens)
