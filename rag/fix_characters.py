# fix_characters.py
from pymilvus import MilvusClient, DataType
import numpy as np
import pickle
import json
import time

DATA_DIR = "./data"
COLLECTION = "characters"
DIM = 1024

client = MilvusClient(uri="http://localhost:19530")

# 기존 컬렉션 삭제 후 재생성
if client.has_collection(COLLECTION):
    client.drop_collection(COLLECTION)
    print("기존 컬렉션 삭제")

schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
schema.add_field("id",             DataType.INT64,              is_primary=True)
schema.add_field("character_name", DataType.VARCHAR,             max_length=100)
schema.add_field("movie",          DataType.VARCHAR,             max_length=200)
schema.add_field("lang",           DataType.VARCHAR,             max_length=10)
schema.add_field("data_type",      DataType.VARCHAR,             max_length=20)
schema.add_field("text",           DataType.VARCHAR,             max_length=4000)
schema.add_field("metadata",       DataType.VARCHAR,             max_length=8000)
schema.add_field("dense_vector",   DataType.FLOAT_VECTOR,        dim=DIM)
schema.add_field("sparse_vector",  DataType.SPARSE_FLOAT_VECTOR)

index_params = client.prepare_index_params()
index_params.add_index("dense_vector",  metric_type="COSINE", index_type="IVF_FLAT", params={"nlist": 128})
index_params.add_index("sparse_vector", metric_type="IP",     index_type="SPARSE_INVERTED_INDEX")

client.create_collection(COLLECTION, schema=schema, index_params=index_params)
print("✅ 컬렉션 생성 완료")

# 데이터 로드
with open(f'{DATA_DIR}/character_chunks.json', 'r', encoding='utf-8') as f:
    chunks = json.load(f)
dense_vecs = np.load(f'{DATA_DIR}/character_dense_vecs.npy').astype('float32')
with open(f'{DATA_DIR}/character_sparse_vecs.pkl', 'rb') as f:
    sparse_vecs = pickle.load(f)

CHARACTERS_LANG = {
    "마석도": "ko", "장첸": "ko", "강해상": "ko", "서도철": "ko", "조태오": "ko",
    "차태식": "ko", "고니": "ko", "고광렬": "ko", "강림": "ko", "해원맥": "ko",
    "우장훈": "ko", "안옥윤": "ko", "석우": "ko", "화림": "ko", "이순신": "ko",
    "토니 스타크": "en", "스티브 로저스": "en", "피터 파커": "en", "토르": "en",
    "로키": "en", "닥터 스트레인지": "en", "브루스 배너": "en", "스타로드": "en",
    "데드풀": "en", "타노스": "en", "브루스 웨인": "en", "조커": "en",
    "할리 퀸": "en", "슈퍼맨": "en", "원더우먼": "en", "해리포터": "en",
    "헤르미온느": "en", "론 위즐리": "en", "세베루스 스네이프": "en",
    "알버스 덤블도어": "en", "간달프": "en", "프로도": "en", "골룸": "en",
    "네오": "en", "쿠퍼": "en", "코브": "en", "폴 아트레이데스": "en",
    "오펜하이머": "en", "존 윅": "en", "에단 헌트": "en", "매버릭": "en",
    "잭 스패로우": "en", "엘사": "en", "슈렉": "en", "우디": "en",
}

# 삽입
BATCH = 100
total = 0

for i in range(0, len(chunks), BATCH):
    batch_chunks = chunks[i:i+BATCH]
    batch_dense  = dense_vecs[i:i+BATCH]
    batch_sparse = sparse_vecs[i:i+BATCH]

    data = []
    for j, c in enumerate(batch_chunks):
        data.append({
            "character_name": c['character_name'],
            "movie":          c['movie'],
            "lang":           CHARACTERS_LANG.get(c['character_name'], 'ko'),
            "data_type":      c['data_type'],
            "text":           c['text'][:4000],
            "metadata":       json.dumps(c['metadata'], ensure_ascii=False)[:8000],
            "dense_vector":   batch_dense[j].tolist(),
            "sparse_vector":  batch_sparse[j],
        })

    client.insert(COLLECTION, data)
    total += len(data)

# flush 후 확인
client.flush(collection_name=COLLECTION)
time.sleep(3)

stats = client.get_collection_stats(COLLECTION)
print(f"\n{'='*40}")
print(f"✅ 총 {total}개 삽입 완료")
print(f"row_count: {stats['row_count']}")
print(f"{'='*40}")