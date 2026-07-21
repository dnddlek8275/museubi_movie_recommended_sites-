"""
CineVerse Character Retriever
Milvus characters 컬렉션 하이브리드 검색
스키마: character_name / movie / lang / data_type / text / metadata / dense_vector / sparse_vector
"""

from functools import lru_cache

from pymilvus import MilvusClient, AnnSearchRequest, RRFRanker

from rag.embedder import embed_query
from rag.reranker import rerank

MILVUS_URI       = "http://localhost:19530"
COLLECTION_NAME  = "characters"


@lru_cache(maxsize=1)
def get_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


def retrieve(
    character_name: str,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """
    캐릭터 이름으로 필터링 후 쿼리와 유사한 청크를 검색.

    흐름:
        BGE-M3 임베딩 → Hybrid Search (Dense + Sparse + RRF) → CrossEncoder 리랭킹

    Args:
        character_name: 검색할 캐릭터 이름
        query:          사용자 메시지
        top_k:          최종 반환 개수

    Returns:
        재순위된 청크 리스트 (data_type, text 포함)
    """
    client = get_client()
    dense, sparse = embed_query(query)
    filter_expr   = f'character_name == "{character_name}"'
    fetch_limit   = top_k * 3  # 리랭킹 전 후보 수

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
            output_fields=["character_name", "data_type", "text"],
        )
        hits = results[0] if results else []
    except Exception as e:
        print(f"  [CharacterRetriever] hybrid_search 실패, fallback query: {e}")
        hits = []

    # fallback: 메타 필터 조회
    if not hits:
        rows = client.query(
            collection_name=COLLECTION_NAME,
            filter=filter_expr,
            output_fields=["data_type", "text"],
            limit=top_k,
        )
        return rows

    candidates = [
        {
            "data_type": h["entity"]["data_type"],
            "text":      h["entity"]["text"],
        }
        for h in hits
    ]

    # CrossEncoder 리랭킹
    ranked = rerank(query, candidates, text_key="text", top_k=top_k * 2)

    # profile 청크 우선 배치
    profiles = [c for c in ranked if c.get("data_type") == "profile"]
    others   = [c for c in ranked if c.get("data_type") != "profile"]
    final    = (profiles + others)[:top_k]

    return final


def format_context(chunks: list[dict]) -> str:
    """청크 리스트를 프롬프트 주입용 문자열로 변환"""
    return "\n\n".join(c["text"] for c in chunks if c.get("text"))
