"""
CineVerse RAG Reranker
CrossEncoder (BGE-Reranker-v2-m3) 싱글턴
"""

from functools import lru_cache
from sentence_transformers import CrossEncoder

MODEL_NAME = "BAAI/bge-reranker-v2-m3"


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """CrossEncoder 싱글턴 (최초 1회 로드).

    GPU에 유지한다. 실측 결과 후보 9개(최대 512토큰)만 재랭킹해도
    CPU에서는 ~6.5s, GPU에서는 <1s로 차이가 커서 GPU가 필수적이다.
    """
    return CrossEncoder(MODEL_NAME, max_length=512)


def rerank(
    query: str,
    candidates: list[dict],
    text_key: str = "text",
    top_k: int | None = None,
) -> list[dict]:
    """
    후보 문서를 CrossEncoder로 재순위 후 반환.

    Args:
        query:      검색 쿼리
        candidates: 후보 문서 리스트 (각 dict에 text_key 필드 포함)
        text_key:   점수 계산에 사용할 텍스트 필드명
        top_k:      상위 몇 개만 반환 (None이면 전체)

    Returns:
        score 필드가 추가된 dict 리스트 (내림차순 정렬)
    """
    if not candidates:
        return []

    reranker = get_reranker()
    pairs  = [[query, c[text_key]] for c in candidates]
    scores = reranker.predict(pairs)

    ranked = sorted(
        [dict(c, _score=float(s)) for c, s in zip(candidates, scores)],
        key=lambda x: x["_score"],
        reverse=True,
    )

    return ranked[:top_k] if top_k else ranked
