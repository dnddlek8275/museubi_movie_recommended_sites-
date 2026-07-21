"""
CineVerse Movie Retriever
Milvus movies 컬렉션 하이브리드 검색
스키마: title / text / overview / genres / director / cast /
        year / language / vote_average / audience_count / poster_path / tmdb_id
"""

from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache

from pymilvus import MilvusClient, AnnSearchRequest, RRFRanker

from rag.embedder import embed_query
from rag.reranker import rerank

MILVUS_URI      = "http://localhost:19530"
COLLECTION_NAME = "movies"

OUTPUT_FIELDS = [
    "title", "text", "overview", "genres", "genres_list",
    "director", "cast", "year", "language",
    "vote_average", "vote_count", "audience_count",
    "poster_path", "tmdb_id",
]


@dataclass
class MovieFilter:
    """영화 검색 메타 필터"""
    genre:      str | None   = None
    actor:      str | None   = None
    director:   str | None   = None
    language:   str | None   = None
    year_from:  int | None   = None
    year_to:    int | None   = None
    min_rating: float | None = None

    def to_expr(self) -> str | None:
        filters = []
        if self.genre:
            filters.append(f'genres like "%{self.genre}%"')
        if self.actor:
            filters.append(f'cast like "%{self.actor}%"')
        if self.director:
            filters.append(f'director like "%{self.director}%"')
        if self.language:
            filters.append(f'language == "{self.language}"')
        if self.year_from:
            filters.append(f'year >= {self.year_from}')
        if self.year_to:
            filters.append(f'year <= {self.year_to}')
        if self.min_rating:
            filters.append(f'vote_average >= {self.min_rating}')
        return " and ".join(filters) if filters else None


@lru_cache(maxsize=1)
def get_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


def retrieve(
    query: str,
    top_k: int = 5,
    movie_filter: MovieFilter | None = None,
) -> list[dict]:
    """
    영화를 하이브리드 검색 후 CrossEncoder로 재순위.

    흐름:
        BGE-M3 임베딩 → Hybrid Search (Dense + Sparse + RRF) → CrossEncoder 리랭킹

    Args:
        query:        검색 쿼리 (자연어)
        top_k:        최종 반환 개수
        movie_filter: 메타 필터 조건

    Returns:
        재순위된 영화 dict 리스트
    """
    client      = get_client()
    dense, sparse = embed_query(query)
    fetch_limit = top_k * 3
    filter_expr = movie_filter.to_expr() if movie_filter else None

    dense_req = AnnSearchRequest(
        data=[dense],
        anns_field="dense_vector",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=fetch_limit,
        expr=filter_expr,
    )
    sparse_req = AnnSearchRequest(
        data=[sparse],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=fetch_limit,
        expr=filter_expr,
    )

    try:
        results = client.hybrid_search(
            collection_name=COLLECTION_NAME,
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(k=60),
            limit=fetch_limit,
            output_fields=OUTPUT_FIELDS,
        )
        hits = results[0] if results else []
    except Exception as e:
        print(f"  [MovieRetriever] hybrid_search 실패: {e}")
        return []

    if not hits:
        return []

    candidates = [h["entity"] for h in hits]

    # CrossEncoder 리랭킹
    ranked = rerank(query, candidates, text_key="text", top_k=top_k)

    # _score 필드 제거 후 반환
    return [{k: v for k, v in m.items() if k != "_score"} for m in ranked]


def format_for_prompt(movies: list[dict], max_overview: int = 200) -> str:
    """영화 목록을 LLM 프롬프트 주입용 텍스트로 변환"""
    if not movies:
        return ""
    lines = []
    for i, m in enumerate(movies, 1):
        lines.append(
            f"{i}. {m.get('title', '')} ({m.get('year', '')})\n"
            f"   장르: {m.get('genres', '')}\n"
            f"   감독: {m.get('director', '')}\n"
            f"   출연: {str(m.get('cast', ''))[:100]}\n"
            f"   평점: {round(float(m['vote_average']), 1) if m.get('vote_average') is not None else '-'}\n"
            f"   줄거리: {str(m.get('overview', ''))[:max_overview]}"
        )
    return "\n\n".join(lines)


def to_response(movies: list[dict]) -> list[dict]:
    """프론트엔드 응답용 영화 dict로 변환 (필요한 필드만, poster_url 풀 URL)"""
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
    return [
        {
            "title":        m.get("title", ""),
            "year":         m.get("year", ""),
            "genres":       m.get("genres", ""),
            "director":     m.get("director", ""),
            "cast":         m.get("cast", ""),
            "vote_average": round(float(m["vote_average"]), 1) if m.get("vote_average") is not None else None,
            "overview":     m.get("overview", ""),
            "poster_url":   f"{TMDB_IMAGE_BASE}{m['poster_path']}" if m.get("poster_path") else "",
            "tmdb_id":      m.get("tmdb_id", ""),
        }
        for m in movies
    ]