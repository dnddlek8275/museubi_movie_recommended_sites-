"""
CineVerse Query Rewriter
사용자의 자연어 입력을 영화 검색에 최적화된 쿼리로 재작성.

처리 전략:
  1단계: regex로 배우/장르/연도/평점/언어를 빠르게 추출 (~0ms)
  2단계: LLM으로 search_query 정제 + 1단계에서 못 잡은 필드 보완 (~4s)
  LLM이 실패하면 1단계 결과만으로 fallback.
"""

import json
import re

from llm.client import chat_json

# ── 1단계: 빠른 regex 추출 ──────────────────────────────────────

# 주요 배우 이름 (자주 검색되는 인물 위주)
_ACTOR_PATTERNS = re.compile(
    r"마동석|송강호|최민식|이병헌|공유|하정우|황정민|유아인|조인성|현빈|"
    r"강동원|박서준|이제훈|류준열|손석구|오달수|이성민|박해일|설경구|"
    r"전지현|김혜수|손예진|이영애|한가인|공효진|이나영|김고은|박소담|"
    r"탕웨이|배두나|문소리|나문희|윤여정|"
    r"마동석|톰 크루즈|Tom Cruise|레오나르도 디카프리오|Brad Pitt|브래드 피트",
    re.IGNORECASE,
)

_GENRE_MAP = {
    "액션": "액션", "action": "액션",
    "로맨스": "로맨스", "romance": "로맨스", "멜로": "로맨스",
    "공포": "공포", "horror": "공포", "호러": "공포",
    "코미디": "코미디", "comedy": "코미디", "웃긴": "코미디",
    "스릴러": "스릴러", "thriller": "스릴러",
    "SF": "SF", "sci-fi": "SF", "공상과학": "SF",
    "판타지": "판타지", "fantasy": "판타지",
    "애니": "애니메이션", "애니메이션": "애니메이션", "animation": "애니메이션",
    "다큐": "다큐멘터리", "다큐멘터리": "다큐멘터리", "documentary": "다큐멘터리",
    "드라마": "드라마", "drama": "드라마",
    "범죄": "범죄", "crime": "범죄",
    "전쟁": "전쟁", "war": "전쟁",
    "역사": "역사", "historical": "역사",
    "미스터리": "미스터리", "mystery": "미스터리",
    "뮤지컬": "뮤지컬", "musical": "뮤지컬",
}
_GENRE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _GENRE_MAP) + r")\b",
    re.IGNORECASE,
)

_YEAR_RANGE  = re.compile(r"(\d{4})\s*[-~]\s*(\d{4})")
_YEAR_AFTER  = re.compile(r"(\d{4})\s*년?\s*(?:이후|부터|이상)")
_YEAR_BEFORE = re.compile(r"(\d{4})\s*년?\s*(?:이전|까지|이하)")
_YEAR_SINGLE = re.compile(r"(19|20)\d{2}년?")
_YEAR_DECADE = re.compile(r"(19|20)(\d0)년대")

_RATING_PATTERN = re.compile(r"평점\s*(\d+(?:\.\d+)?)\s*(?:점|이상|↑)?")

_LANG_MAP = {"한국": "ko", "한국어": "ko", "영어": "en", "영미": "en",
             "일본": "ja", "일본어": "ja", "중국": "zh", "중국어": "zh",
             "프랑스": "fr", "프랑스어": "fr"}
_LANG_PATTERN = re.compile(r"(" + "|".join(_LANG_MAP) + r")\s*(?:영화|작품)?")

# 감독 추출: "[이름] 감독" 패턴
_DIRECTOR_PATTERN = re.compile(r"([가-힣A-Za-z\s·]{2,20}?)\s*감독")

# LLM이 반환하는 영문 장르를 한국어로 정규화
_GENRE_NORMALIZE = {
    "science fiction": "SF", "sci-fi": "SF", "sf": "SF",
    "action": "액션", "romance": "로맨스", "horror": "공포",
    "comedy": "코미디", "thriller": "스릴러", "fantasy": "판타지",
    "animation": "애니메이션", "documentary": "다큐멘터리", "drama": "드라마",
    "crime": "범죄", "war": "전쟁", "history": "역사", "historical": "역사",
    "mystery": "미스터리", "musical": "뮤지컬",
}


def _regex_extract(text: str) -> dict:
    """regex로 필드 빠르게 추출. 없으면 None."""
    result = {
        "search_query": text,
        "genre": None, "actor": None, "director": None,
        "language": None, "year_from": None, "year_to": None, "min_rating": None,
    }

    # 배우
    m = _ACTOR_PATTERNS.search(text)
    if m:
        result["actor"] = m.group(0)

    # 감독 ("XXX 감독" 패턴)
    m = _DIRECTOR_PATTERN.search(text)
    if m:
        result["director"] = m.group(1).strip()

    # 장르
    m = _GENRE_PATTERN.search(text)
    if m:
        result["genre"] = _GENRE_MAP.get(m.group(1).lower(), m.group(1))

    # 연도 범위 (우선순위: 범위 > 이후/이전(개방형) > 년대 > 단일)
    m = _YEAR_RANGE.search(text)
    if m:
        result["year_from"], result["year_to"] = int(m.group(1)), int(m.group(2))
    else:
        m_after  = _YEAR_AFTER.search(text)
        m_before = _YEAR_BEFORE.search(text)
        if m_after:
            result["year_from"] = int(m_after.group(1))  # year_to는 상한 없이 null 유지
        elif m_before:
            result["year_to"] = int(m_before.group(1))   # year_from은 하한 없이 null 유지
        else:
            m = _YEAR_DECADE.search(text)
            if m:
                base = int(m.group(1) + m.group(2))
                result["year_from"], result["year_to"] = base, base + 9
            else:
                m = _YEAR_SINGLE.search(text)
                if m:
                    y = int(m.group(0).rstrip("년"))
                    result["year_from"] = result["year_to"] = y

    # 평점
    m = _RATING_PATTERN.search(text)
    if m:
        result["min_rating"] = float(m.group(1))

    # 언어
    m = _LANG_PATTERN.search(text)
    if m:
        result["language"] = _LANG_MAP.get(m.group(1))

    return result


# ── 2단계: LLM 보완 ─────────────────────────────────────────────

REWRITE_SYSTEM = """너는 영화 검색 쿼리 분석 전문가다.
사용자의 자연어 입력을 분석해서 아래 JSON 형식으로만 응답해라. 다른 말은 하지 마라.

{
  "search_query": "벡터 검색에 최적화된 핵심 쿼리",
  "genre": "장르 (없으면 null)",
  "actor": "배우 이름 (없으면 null)",
  "director": "감독 이름 (없으면 null)",
  "language": "언어코드 ko/en/ja 등 (없으면 null)",
  "year_from": 시작연도 정수 (없으면 null),
  "year_to": 종료연도 정수 (없으면 null),
  "min_rating": 최소평점 실수 (없으면 null)
}

절대 규칙: 사용자 문장에 실제로 등장하지 않은 정보는 절대 추측해서 채우지 마라.
필드 하나를 채울 근거가 있어도 다른 필드까지 덩달아 채우면 안 된다. 애매하면 null이다."""

# 텍스트 예시 대신 실제 대화 턴으로 few-shot을 준다.
# (예시를 시스템 프롬프트 안에 텍스트로 넣으면 모델이 JSON 대신 "다음 예시"를
#  이어서 생성하려는 경향이 있어, 실제 user/assistant 턴으로 분리해야 안정적으로 지켜짐)
_FEWSHOT_TURNS = [
    ("액션 영화 추천해줘",
     '{"search_query": "액션 영화", "genre": "액션", "actor": null, "director": null, "language": null, "year_from": null, "year_to": null, "min_rating": null}'),
    ("마동석 나오는 영화 있어?",
     '{"search_query": "마동석 영화", "genre": null, "actor": "마동석", "director": null, "language": null, "year_from": null, "year_to": null, "min_rating": null}'),
    ("봉준호 감독 영화",
     '{"search_query": "봉준호 감독 영화", "genre": null, "actor": null, "director": "봉준호", "language": null, "year_from": null, "year_to": null, "min_rating": null}'),
    ("2020년 이후 영화",
     '{"search_query": "2020년 이후 영화", "genre": null, "actor": null, "director": null, "language": null, "year_from": 2020, "year_to": null, "min_rating": null}'),
]


# LLM이 가끔 필드 이름을 살짝 틀리게 쓰는 경우(예: search_of_query)를 정규 이름으로 매핑
_KEY_ALIASES = {
    "search_of_query": "search_query", "searchquery": "search_query", "query": "search_query",
}


def _parse_llm_json(raw: str, fallback: dict) -> dict:
    """LLM 출력 JSON 파싱. 실패하면 fallback 반환."""
    try:
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        # JSON 앞뒤에 섞여 나오는 잡음 문자(예: 여는 중괄호 뒤 '<') 제거
        cleaned = re.sub(r'([{,]\s*)[^\s"{}\[\],:]*"', r'\1"', cleaned)
        cleaned = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', cleaned)
        cleaned = re.sub(r'""([^"]+)""(\s*:)', r'"\1"\2', cleaned)
        result  = json.loads(cleaned)
        result  = {_KEY_ALIASES.get(k.lstrip("_"), k.lstrip("_")): v for k, v in result.items()}
        if not result.get("search_query"):
            result["search_query"] = fallback["search_query"]
        return result
    except Exception as e:
        print(f"  [QueryRewriter] LLM JSON 파싱 실패, regex 결과 사용: {e}")
        return fallback


_RATING_MENTION = re.compile(r"평점|rating|별점")


def _validate_against_text(llm: dict, pre: dict, user_message: str) -> dict:
    """LLM이 채운 필드가 실제 사용자 문장에 근거가 있는지 검증. 없으면 버린다(null).

    파인튜닝된 모델이 이 추출 작업에서 불안정하게 필드를 지어내는 경향이 있어
    (예: 장르만 말했는데 평점·연도까지 채움), 프롬프트만으로는 완전히 못 잡는다.
    코드 레벨에서 텍스트 근거 없는 값은 신뢰하지 않는 안전장치를 둔다.
    """
    # 연도: regex가 찾은 신호를 기준으로 LLM 값의 범위를 강제한다.
    # - 둘 다 못 찾았으면 LLM 값도 전부 버린다.
    # - 한쪽만 찾았다면(예: "2020년 이후") 그건 개방형 범위라는 뜻이므로
    #   반대쪽 경계는 LLM이 뭘 채우든 무조건 null로 강제한다.
    pre_from, pre_to = pre.get("year_from"), pre.get("year_to")
    if pre_from is None and pre_to is None:
        llm["year_from"] = None
        llm["year_to"] = None
    elif pre_from is not None and pre_to is None:
        llm["year_from"] = llm.get("year_from") or pre_from
        llm["year_to"] = None
    elif pre_to is not None and pre_from is None:
        llm["year_to"] = llm.get("year_to") or pre_to
        llm["year_from"] = None

    # 평점: "평점/rating/별점" 언급이 실제로 없으면 LLM이 채운 값도 버린다
    if not _RATING_MENTION.search(user_message):
        llm["min_rating"] = None

    # 배우/감독: LLM이 채운 이름이 실제 문장에 없으면 지어낸 것으로 간주해 버린다
    for field in ("actor", "director"):
        val = llm.get(field)
        if val and str(val) not in user_message:
            llm[field] = None

    return llm


# regex가 이 필드들 중 하나라도 찾았으면 LLM 호출을 생략한다.
_PRE_FIELDS = ("genre", "actor", "director", "language", "year_from", "year_to", "min_rating")


def rewrite(user_message: str) -> dict:
    """
    사용자 입력을 분석해서 검색 쿼리 + 메타 필터를 추출.

    Returns:
        {"search_query", "genre", "actor", "director", "language",
         "year_from", "year_to", "min_rating"}
    """
    # 1단계: regex 빠른 추출
    pre = _regex_extract(user_message)

    # regex가 이미 뭔가 찾았으면 LLM 호출 자체를 생략한다.
    # 검증 가드(_validate_against_text)가 regex 근거 없는 LLM 값은 어차피 버리기 때문에,
    # 이 경우 LLM 호출은 실질적 가치 없이 2~5초만 더 든다. regex가 아무것도 못 찾은
    # 애매한 자유 발화일 때만 LLM으로 보완한다.
    if any(pre.get(f) is not None for f in _PRE_FIELDS):
        return pre

    # 2단계: LLM으로 search_query 정제 + 미추출 필드 보완
    # 이 모델은 영화 추천/캐릭터 대화로 파인튜닝되어 있어서, "영화 추천해줘" 같은
    # 문구를 보면 JSON 대신 캐릭터 페르소나로 답하려는 경향이 있다.
    # 생성 직전(마지막 유저 메시지)에 "이건 추천이 아니라 추출 작업"이라고 못박아서 방지한다.
    messages = [{"role": "system", "content": REWRITE_SYSTEM}]
    for q, a in _FEWSHOT_TURNS:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({
        "role": "user",
        "content": (
            f"{user_message}\n\n"
            "[중요] 이건 영화 추천 요청이 아니다. 위 문장을 검색 필터 JSON으로 변환하는 작업이다. "
            "영화를 추천하거나 설명하지 마라. 대사·감상평을 쓰지 마라. "
            "오직 JSON 객체 하나만 출력해라."
        ),
    })
    raw = chat_json(messages, max_tokens=400)
    llm = _parse_llm_json(raw, pre)
    llm = _validate_against_text(llm, pre, user_message)

    # regex 결과로 LLM 누락 필드 보완 (LLM 우선, regex는 보조)
    for field in ("genre", "actor", "director", "language", "year_from", "year_to", "min_rating"):
        if llm.get(field) is None and pre.get(field) is not None:
            llm[field] = pre[field]

    # LLM 장르 정규화: 영문→한국어, 복수 값은 첫 번째만 사용
    if llm.get("genre"):
        g = str(llm["genre"]).strip()
        # "horror, thriller" → "horror"
        g = g.split(",")[0].split("/")[0].strip()
        g = _GENRE_NORMALIZE.get(g.lower(), _GENRE_MAP.get(g, g))
        llm["genre"] = g

    return llm
