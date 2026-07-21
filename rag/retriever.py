"""
CineVerse RAG Retriever
- characters 컬렉션: 캐릭터 기억/경험 검색
- movies 컬렉션: 영화 추천 검색
- BGE-M3 하이브리드 (Dense + Sparse) + RRF + CrossEncoder 리랭커
"""

from __future__ import annotations
from functools import lru_cache

from pymilvus import MilvusClient, AnnSearchRequest, RRFRanker
from FlagEmbedding import BGEM3FlagModel
from sentence_transformers import CrossEncoder

MILVUS_URI = "http://localhost:19530"
BGE_MODEL_NAME = "BAAI/bge-m3"
RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


@lru_cache(maxsize=1)
def get_embedder() -> BGEM3FlagModel:
    return BGEM3FlagModel(BGE_MODEL_NAME, use_fp16=True)


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER_MODEL_NAME, max_length=512)


@lru_cache(maxsize=1)
def get_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


def embed_query(query: str) -> tuple[list[float], dict]:
    embedder = get_embedder()
    result = embedder.encode(
        [query],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = result["dense_vecs"][0].tolist()
    sparse = result["lexical_weights"][0]
    sparse_dict = {int(k): float(v) for k, v in sparse.items()}
    return dense, sparse_dict


def get_character_context(
    character_name: str,
    query: str,
    limit: int = 5,
) -> str:
    client = get_client()
    dense, sparse = embed_query(query)
    filter_expr = f'character_name == "{character_name}"'

    dense_req = AnnSearchRequest(
        data=[dense],
        anns_field="dense_vector",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=limit * 2,
        expr=filter_expr,
    )
    sparse_req = AnnSearchRequest(
        data=[sparse],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=limit * 2,
        expr=filter_expr,
    )

    try:
        results = client.hybrid_search(
            collection_name="characters",
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(k=60),
            limit=limit * 2,
            output_fields=["character_name", "data_type", "text"],
        )
    except Exception:
        results = None

    if not results or not results[0]:
        rows = client.query(
            collection_name="characters",
            filter=filter_expr,
            output_fields=["data_type", "text"],
            limit=limit,
        )
        return "\n\n".join(r["text"] for r in rows)

    hits = results[0]
    candidates = [
        {"text": h["entity"]["text"], "data_type": h["entity"]["data_type"]}
        for h in hits
    ]

    if not candidates:
        return ""

    reranker = get_reranker()
    pairs = [[query, c["text"]] for c in candidates]
    scores = reranker.predict(pairs)

    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

    top = [c for c, _ in ranked[:limit]]
    profiles = [c for c in top if c["data_type"] == "profile"]
    others = [c for c in top if c["data_type"] != "profile"]
    final = (profiles + others)[:limit]

    return "\n\n".join(c["text"] for c in final)


def search_movies(
    query: str,
    limit: int = 5,
    genre: str | None = None,
    actor: str | None = None,
    director: str | None = None,
    language: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    min_rating: float | None = None,
) -> list[dict]:
    client = get_client()
    dense, sparse = embed_query(query)

    filters = []
    if genre:
        filters.append(f'genres like "%{genre}%"')
    if actor:
        filters.append(f'cast like "%{actor}%"')
    if director:
        filters.append(f'director like "%{director}%"')
    if language:
        filters.append(f'language == "{language}"')
    if year_from:
        filters.append(f'year >= {year_from}')
    if year_to:
        filters.append(f'year <= {year_to}')
    if min_rating:
        filters.append(f'vote_average >= {min_rating}')
    filter_expr = " and ".join(filters) if filters else None

    output_fields = [
        "title", "text", "overview", "genres", "director", "cast",
        "year", "language", "vote_average", "audience_count",
        "poster_path", "tmdb_id",
    ]

    dense_req = AnnSearchRequest(
        data=[dense],
        anns_field="dense_vector",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=limit * 2,
        expr=filter_expr,
    )
    sparse_req = AnnSearchRequest(
        data=[sparse],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=limit * 2,
        expr=filter_expr,
    )

    try:
        results = client.hybrid_search(
            collection_name="movies",
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(k=60),
            limit=limit * 2,
            output_fields=output_fields,
        )
    except Exception:
        return []

    if not results or not results[0]:
        return []

    hits = results[0]
    candidates = [h["entity"] for h in hits]

    if not candidates:
        return []

    reranker = get_reranker()
    pairs = [[query, c["text"]] for c in candidates]
    scores = reranker.predict(pairs)

    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:limit]]


def format_movies_for_prompt(movies: list[dict]) -> str:
    if not movies:
        return ""
    lines = []
    for i, m in enumerate(movies, 1):
        line = (
            f"{i}. {m.get('title', '')} ({m.get('year', '')})\n"
            f"   장르: {m.get('genres', '')}\n"
            f"   감독: {m.get('director', '')}\n"
            f"   출연: {m.get('cast', '')[:100]}\n"
            f"   평점: {m.get('vote_average', '')}\n"
            f"   줄거리: {m.get('overview', '')[:200]}"
        )
        lines.append(line)
    return "\n\n".join(lines)