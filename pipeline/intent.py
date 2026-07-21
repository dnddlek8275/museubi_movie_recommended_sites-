"""
CineVerse Intent Classifier
사용자 입력을 영화 추천 / 캐릭터 대화로 분류.
LLM 호출 없이 키워드 기반으로 빠르게 처리.
"""

import re

# 영화 추천 관련 키워드
_MOVIE_PATTERNS = re.compile(
    r"영화\s*추천|뭐\s*볼까|볼만한|추천해\s*줘|추천\s*좀|"
    r"비슷한\s*영화|장르|감독|배우|개봉|평점|"
    r"액션|로맨스|공포|코미디|스릴러|SF|판타지|애니|다큐|"
    r"넷플|왓챠|티빙|OTT|스트리밍|"
    r"나오는\s*(?:영화|거|것)|뭐\s*있어|뭐\s*봐|영화\s*있어|"
    r"시리즈|작품|감상|봤어|볼\s*게|흥행",
    re.IGNORECASE,
)

# 캐릭터 대화 관련 키워드 (영화 추천보다 우선순위 낮음)
_CHAT_PATTERNS = re.compile(
    r"어떻게\s*생각|조언|고민|힘들|슬프|화가|무서|"
    r"취업|사업|연애|친구|가족|돈|공부|일",
    re.IGNORECASE,
)


class Intent:
    MOVIE_RECOMMEND = "movie_recommend"
    CHARACTER_CHAT  = "character_chat"


def classify(user_message: str) -> str:
    """
    사용자 입력의 인텐트를 분류.

    Returns:
        Intent.MOVIE_RECOMMEND or Intent.CHARACTER_CHAT
    """
    if _MOVIE_PATTERNS.search(user_message):
        return Intent.MOVIE_RECOMMEND

    return Intent.CHARACTER_CHAT
