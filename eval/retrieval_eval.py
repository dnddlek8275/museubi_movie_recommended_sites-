"""
영화 검색 성능(Hit@10) 평가 스크립트

방법론:
    Milvus movies 컬렉션에서 무작위로 N편을 뽑아, 각 영화의 줄거리(overview) 앞부분을
    "사용자가 입력할 법한 쿼리"로 삼는다. 그 쿼리로 검색했을 때 원래 영화 제목이
    top-10 안에 들어오면 Hit, 아니면 Miss로 집계한다.

    같은 테스트셋으로 3가지 검색 방식을 비교한다 (실제 API 서버의 이미 로드된
    임베더/리랭커를 재사용하기 위해 /debug/movie_retrieve 엔드포인트를 통해 호출):
    - v1 dense   : BGE-M3 dense 벡터만 사용한 단순 코사인 검색
    - v2 hybrid  : dense + sparse 하이브리드 검색 (RRF 결합), 리랭킹 없음
    - v3 rerank  : v2 + CrossEncoder(BGE-Reranker-v2-m3) 재순위 (현재 프로덕션 방식)

사용법:
    venv/bin/python3 eval/retrieval_eval.py
"""

import json
import random
from pathlib import Path

import requests
from pymilvus import MilvusClient

_BASE_DIR = Path(__file__).parent.parent
API_BASE  = "http://localhost"
MILVUS_URI = "http://localhost:19530"

N_SAMPLES = 60
QUERY_LEN = 60  # overview 앞부분 몇 글자를 쿼리로 쓸지
MODES = ["dense", "hybrid", "rerank"]
MODE_LABEL = {"dense": "v1 (dense only)", "hybrid": "v2 (hybrid, no rerank)", "rerank": "v3 (hybrid + rerank)"}


def build_test_set(n: int, seed: int = 42) -> list[dict]:
    client = MilvusClient(uri=MILVUS_URI)
    rows = client.query(
        collection_name="movies",
        filter='year > 1990',
        output_fields=["title", "overview"],
        limit=5000,
    )
    rows = [r for r in rows if r.get("overview") and len(r["overview"]) >= QUERY_LEN + 10]
    random.seed(seed)
    sample = random.sample(rows, min(n, len(rows)))

    test_set = []
    for r in sample:
        overview = r["overview"].strip()
        query = overview[:QUERY_LEN].rsplit(" ", 1)[0]  # 단어 중간 끊김 방지
        test_set.append({"title": r["title"], "query": query})
    return test_set


def retrieve(query: str, mode: str, top_k: int = 10) -> list[str]:
    r = requests.post(f"{API_BASE}/debug/movie_retrieve", json={
        "query": query, "top_k": top_k, "mode": mode,
    }, timeout=30)
    r.raise_for_status()
    return r.json()["titles"]


def main():
    print(f"테스트셋 구성 중 (목표 {N_SAMPLES}개)...")
    test_set = build_test_set(N_SAMPLES)
    print(f"테스트셋 {len(test_set)}개 완료\n")

    per_query_results = []
    ranks = {m: [] for m in MODES}  # 못 찾으면 None

    for i, case in enumerate(test_set, 1):
        row = {"title": case["title"], "query": case["query"]}
        for mode in MODES:
            titles = retrieve(case["query"], mode)
            rank = titles.index(case["title"]) + 1 if case["title"] in titles else None
            row[mode] = rank
            ranks[mode].append(rank)
        per_query_results.append(row)
        print(f"[{i}/{len(test_set)}] {case['title']!r:30s} "
              f"dense={row['dense']!s:5s} hybrid={row['hybrid']!s:5s} rerank={row['rerank']!s:5s}")

    def stats(mode_ranks: list) -> dict:
        n = len(mode_ranks)
        hit1  = sum(1 for r in mode_ranks if r is not None and r <= 1) / n * 100
        hit3  = sum(1 for r in mode_ranks if r is not None and r <= 3) / n * 100
        hit10 = sum(1 for r in mode_ranks if r is not None and r <= 10) / n * 100
        mrr   = sum((1 / r) if r is not None else 0 for r in mode_ranks) / n
        return {"hit@1": round(hit1, 1), "hit@3": round(hit3, 1), "hit@10": round(hit10, 1), "mrr": round(mrr, 3)}

    print("\n" + "=" * 66)
    print(f"검색 성능 결과 (테스트셋 {len(test_set)}개, 쿼리=영화 줄거리 앞부분 {QUERY_LEN}자)")
    print("=" * 66)
    summary = {}
    print(f"{'':<28s}{'Hit@1':>8s}{'Hit@3':>8s}{'Hit@10':>8s}{'MRR':>8s}")
    for mode in MODES:
        s = stats(ranks[mode])
        summary[mode] = s
        print(f"{MODE_LABEL[mode]:<28s}{s['hit@1']:>7.1f}%{s['hit@3']:>7.1f}%{s['hit@10']:>7.1f}%{s['mrr']:>8.3f}")

    out = {
        "n_samples": len(test_set),
        "query_len_chars": QUERY_LEN,
        "summary": summary,
        "per_query": per_query_results,
    }
    out_path = _BASE_DIR / "eval" / "retrieval_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
