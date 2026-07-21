"""
CineVerse RAG Embedder
BGE-M3 Dense + Sparse 임베딩 싱글턴
"""

from functools import lru_cache
from FlagEmbedding import BGEM3FlagModel

MODEL_NAME = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_embedder() -> BGEM3FlagModel:
    """BGE-M3 모델 싱글턴 (최초 1회 로드).

    CPU로 고정 로드한다. GPU(T4 15GB)는 llama-server 전용으로 비워둬서
    동시 처리 슬롯(np) 확보에 쓴다. fp16은 CPU에서 이득이 없어 끈다.
    """
    return BGEM3FlagModel(MODEL_NAME, use_fp16=False, devices="cpu")


def embed(texts: list[str]) -> tuple[list[list[float]], list[dict]]:
    """
    텍스트 리스트를 Dense + Sparse 벡터로 변환.

    Returns:
        (dense_list, sparse_list)
        - dense_list:  각 텍스트의 dense 벡터 (1024차원)
        - sparse_list: 각 텍스트의 sparse 벡터 (dict 형태)
    """
    embedder = get_embedder()
    result = embedder.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )

    dense_list = result["dense_vecs"].tolist()
    sparse_list = [
        {int(k): float(v) for k, v in row.items()}
        for row in result["lexical_weights"]
    ]

    return dense_list, sparse_list


def embed_query(query: str) -> tuple[list[float], dict]:
    """단일 쿼리 임베딩 (검색용 편의 함수)"""
    dense_list, sparse_list = embed([query])
    return dense_list[0], sparse_list[0]
