import json
import numpy as np
import pandas as pd
from tqdm import tqdm
from pymilvus import (
    connections, Collection, CollectionSchema, FieldSchema,
    DataType, utility
)

# ── Milvus 연결 ────────────────────────────────────────────
connections.connect(host='localhost', port='19530')
print("Milvus 연결 완료")

# ── 데이터 로드 ────────────────────────────────────────────
DATA_DIR = './data'

print("데이터 로드 중...")
df = pd.read_csv(f'{DATA_DIR}/movies_final.csv')
dense_vecs = np.load(f'{DATA_DIR}/dense_vecs_v3.npy').tolist()
with open(f'{DATA_DIR}/sparse_vecs_v3.json', 'r') as f:
    sparse_vecs = json.load(f)

print(f"영화 수     : {len(df):,}")
print(f"dense 벡터  : {len(dense_vecs):,}")
print(f"sparse 벡터 : {len(sparse_vecs):,}")

# ── 청크 생성 ──────────────────────────────────────────────
GENRE_EN_MAP = {
    '액션': 'Action', '드라마': 'Drama', '코미디': 'Comedy',
    '로맨스': 'Romance', '스릴러': 'Thriller', '공포': 'Horror',
    '미스터리': 'Mystery', '범죄': 'Crime', 'SF': 'Science Fiction',
    '판타지': 'Fantasy', '어드벤처': 'Adventure', '모험': 'Adventure',
    '애니메이션': 'Animation', '가족': 'Family', '역사': 'History',
    '전쟁': 'War', '음악': 'Music', '다큐멘터리': 'Documentary',
    '서부': 'Western', 'TV 영화': 'TV Movie'
}

GENRE_MOOD_MAP = {
    '공포'      : '무서운 오싹한 긴장되는 호러 귀신 공포스러운 스릴',
    '스릴러'    : '긴장감 반전 서스펜스 충격적인 미스터리 추리 손에땀',
    '코미디'    : '유쾌한 웃긴 재미있는 가볍게 힐링 병맛 개그 웃음',
    '로맨스'    : '설레는 달달한 사랑스러운 로맨틱 멜로 첫사랑 이별',
    '드라마'    : '감동적인 여운 진지한 인간적인 눈물 감성 깊이있는',
    '액션'      : '신나는 통쾌한 짜릿한 박진감 화끈한 폭발 전투',
    '애니메이션': '귀여운 가족과 함께 어린이 따뜻한 동심 캐릭터',
    '가족'      : '따뜻한 가족과 함께 감동적인 훈훈한 힐링 명절',
    'SF'        : '우주 미래 과학 상상력 신비로운 로봇 외계인 시간여행',
    '판타지'    : '마법 신비로운 환상적인 이세계 용 요정 모험',
    '범죄'      : '범죄 수사 긴장감 사건 형사 추격 조직',
    '역사'      : '실화 역사적 묵직한 시대배경 역사드라마',
    '전쟁'      : '전쟁 역사 감동 희생 숭고한 군인 전투 나라',
    '미스터리'  : '수수께끼 반전 궁금한 추리 비밀 반전결말',
    '음악'      : '음악 감동 노래 뮤지컬 콘서트 밴드',
    '다큐멘터리': '실화 다큐 사실적인 깊이있는 진짜이야기',
    '모험'      : '모험 탐험 여행 도전 미지의세계 스릴',
    '어드벤처'  : '어드벤처 모험 탐험 여행 액션 스릴',
    '서부'      : '서부 총잡이 황야 복수 카우보이',
}

GENRE_SITUATION_MAP = {
    '공포'      : '혼자 밤에 보기 친구와 함께 오싹한 경험 무서운거 보고싶을때',
    '코미디'    : '가족과 함께 친구들과 기분전환 스트레스 해소 웃고싶을때',
    '로맨스'    : '데이트 연인과 함께 설레는 밤 혼자 감성에 젖고싶을때',
    '드라마'    : '혼자 감성에 젖고 싶을 때 여운 남기고 싶을 때 감동받고싶을때',
    '애니메이션': '아이와 함께 가족 모두 동심으로 주말 나들이',
    '가족'      : '가족과 함께 명절 주말 부모님과 함께',
    '액션'      : '스트레스 해소 신나게 보고 싶을 때 친구들과 함께',
    'SF'        : '상상력 자극 우주 여행 기분 혼자 몰입',
    '판타지'    : '현실 탈출 다른 세계로 혼자 힐링',
    '역사'      : '역사 공부 실화 감동 역사 관심있을때',
    '전쟁'      : '역사 관심있을때 숭고한 감동 남자들이 좋아하는',
    '범죄'      : '긴장감 원할때 수사물 좋아하는 사람',
    '미스터리'  : '반전 원할때 추리 좋아하는 사람 혼자 집중해서',
}

KO_EN_TITLE_MAP = {
    '기생충': 'Parasite',
    '살인의 추억': 'Memories of Murder',
    '올드보이': 'Oldboy',
    '아가씨': 'The Handmaiden',
    '괴물': 'The Host',
    '곡성': 'The Wailing',
    '택시운전사': 'A Taxi Driver',
    '변호인': 'The Attorney',
    '부산행': 'Train to Busan',
    '베테랑': 'Veteran',
    '극한직업': 'Extreme Job',
    '명량': 'The Admiral: Roaring Currents',
    '국제시장': 'Ode to My Father',
    '왕의 남자': 'The King and the Clown',
    '광해, 왕이 된 남자': 'Masquerade',
    '헤어질 결심': 'Decision to Leave',
    '파묘': 'Exhuma',
    '마더': 'Mother',
    '설국열차': 'Snowpiercer',
    '악마를 보았다': 'I Saw the Devil',
    '1987': '1987: When the Day Comes',
    '써니': 'Sunny',
    '건축학개론': 'Architecture 101',
    '엽기적인 그녀': 'My Sassy Girl',
    '범죄도시': 'The Roundup',
    '범죄도시 2': 'The Roundup: No Way Out',
    '범죄도시 3': 'The Roundup: No Mercy',
    '범죄도시 4': 'The Roundup: Punishment',
    '사도': 'The Throne',
    '관상': 'The Face Reader',
    '암살': 'Assassination',
    '도둑들': 'The Thieves',
    '전우치': 'Jeon Woo-chi',
    '군함도': 'The Battleship Island',
    '모가디슈': 'Escape from Mogadishu',
    '서울의 봄': 'Seoul Spring',
}

def build_chunk(row) -> dict:
    title     = str(row.get('title', '') or '')
    orig      = str(row.get('original_title', '') or '')
    genres    = str(row.get('genres', '') or '')
    director  = str(row.get('director', '') or '')
    cast      = str(row.get('cast', '') or '')
    overview  = str(row.get('overview', '') or '')
    runtime   = str(row.get('runtime', '') or '')
    language  = str(row.get('language', '') or '')
    vote_avg  = float(row.get('vote_average', 0) or 0)
    vote_cnt  = int(row.get('vote_count', 0) or 0)
    audience  = int(row.get('audience_count', 0) or 0)
    tmdb_id   = str(row.get('tmdb_id', '') or '')
    poster    = str(row.get('poster_path', '') or '')

    try:
        year = str(int(float(row.get('개봉연도', 0) or 0)))
    except:
        year = ''

    LANG_MAP = {'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어', 'fr': '프랑스어'}
    lang_label   = LANG_MAP.get(language, language)
    audience_fmt = f"{audience:,}명" if audience > 0 else '정보없음'

    genre_list = [g.strip() for g in genres.split(',') if g.strip()]
    genre_with_en = ', '.join(
        f"{g} ({GENRE_EN_MAP.get(g, '')})" if GENRE_EN_MAP.get(g) else g
        for g in genre_list
    )

    mood_tags      = ' '.join(GENRE_MOOD_MAP.get(g, '') for g in genre_list if g in GENRE_MOOD_MAP)
    situation_tags = ' '.join(GENRE_SITUATION_MAP.get(g, '') for g in genre_list if g in GENRE_SITUATION_MAP)

    popularity_tag = ''
    if audience >= 10000000:
        popularity_tag = '천만 관객 대흥행 국민 영화 천만영화'
    elif audience >= 5000000:
        popularity_tag = '오백만 관객 흥행작 대흥행'
    elif audience >= 1000000:
        popularity_tag = '백만 관객 흥행작'

    if vote_avg >= 8.0:
        popularity_tag += ' 평점 높은 명작 추천 걸작'
    elif vote_avg >= 7.0:
        popularity_tag += ' 평점 좋은 영화'

    en_title     = KO_EN_TITLE_MAP.get(title, '')
    en_title_str = f"영문제목: {en_title} ({title})" if en_title else ''

    # 한국 역사 영화만 사극 태그
    sageuk_tag = ''
    if language == 'ko' and '역사' in genre_list:
        sageuk_tag = '사극 시대극 조선시대 고려시대 역사극 궁중 왕 신하 권력 한국사극'

    text = f"""제목: {title}
원제: {orig}
{en_title_str}
장르: {genre_with_en}
감독: {director}
출연: {cast}
개봉연도: {year}년 | 상영시간: {runtime}분 | 언어: {lang_label}
평점: {vote_avg:.1f} (투표수: {vote_cnt:,}) | 관객수: {audience_fmt}
줄거리: {overview}
분위기: {mood_tags}
추천상황: {situation_tags}
인기도: {popularity_tag}
{sageuk_tag}""".strip()

    try:
        year_int = int(float(year)) if year else 0
    except:
        year_int = 0

    return {
        'tmdb_id'        : tmdb_id,
        'text'           : text,
        'title'          : title,
        'genres'         : genres,
        'genres_list'    : json.dumps(genre_list, ensure_ascii=False),
        'director'       : director,
        'cast'           : cast,
        'year'           : year_int,
        'language'       : language,
        'runtime'        : int(float(runtime)) if runtime else 0,
        'vote_average'   : round(vote_avg, 2),
        'vote_count'     : vote_cnt,
        'audience_count' : audience,
        'poster_path'    : poster,
        'overview'       : overview,
    }

print("청크 생성 중...")
docs = [build_chunk(row) for _, row in tqdm(df.iterrows(), total=len(df))]
print(f"청크 생성 완료: {len(docs):,}개")

# ── 컬렉션 생성 ────────────────────────────────────────────
COLLECTION = 'movies'
DENSE_DIM  = 1024

if utility.has_collection(COLLECTION):
    utility.drop_collection(COLLECTION)
    print("기존 컬렉션 삭제")

fields = [
    FieldSchema('id',             DataType.INT64,              is_primary=True, auto_id=True),
    FieldSchema('dense_vector',   DataType.FLOAT_VECTOR,       dim=DENSE_DIM),
    FieldSchema('sparse_vector',  DataType.SPARSE_FLOAT_VECTOR),
    FieldSchema('tmdb_id',        DataType.VARCHAR,            max_length=20),
    FieldSchema('title',          DataType.VARCHAR,            max_length=500),
    FieldSchema('text',           DataType.VARCHAR,            max_length=4096),
    FieldSchema('overview',       DataType.VARCHAR,            max_length=3000),
    FieldSchema('genres',         DataType.VARCHAR,            max_length=200),
    FieldSchema('genres_list',    DataType.VARCHAR,            max_length=500),
    FieldSchema('director',       DataType.VARCHAR,            max_length=500),
    FieldSchema('cast',           DataType.VARCHAR,            max_length=1000),
    FieldSchema('year',           DataType.INT32),
    FieldSchema('language',       DataType.VARCHAR,            max_length=10),
    FieldSchema('runtime',        DataType.INT32),
    FieldSchema('vote_average',   DataType.FLOAT),
    FieldSchema('vote_count',     DataType.INT32),
    FieldSchema('audience_count', DataType.INT64),
    FieldSchema('poster_path',    DataType.VARCHAR,            max_length=500),
]

schema     = CollectionSchema(fields=fields)
collection = Collection(name=COLLECTION, schema=schema)
print(f"컬렉션 '{COLLECTION}' 생성 완료")

collection.create_index(
    field_name='dense_vector',
    index_params={'index_type': 'HNSW', 'metric_type': 'COSINE', 'params': {'M': 16, 'efConstruction': 200}}
)
collection.create_index(
    field_name='sparse_vector',
    index_params={'index_type': 'SPARSE_INVERTED_INDEX', 'metric_type': 'IP', 'params': {'drop_ratio_build': 0.2}}
)
print("인덱스 생성 완료")

# ── 데이터 삽입 ────────────────────────────────────────────
INSERT_BATCH = 500

for i in tqdm(range(0, len(docs), INSERT_BATCH), desc="Milvus 삽입"):
    batch_docs   = docs[i:i+INSERT_BATCH]
    batch_dense  = dense_vecs[i:i+INSERT_BATCH]
    batch_sparse = sparse_vecs[i:i+INSERT_BATCH]

    data = []
    for j, doc in enumerate(batch_docs):
        data.append({
            'dense_vector'   : batch_dense[j],
            'sparse_vector'  : {int(k): float(v) for k, v in batch_sparse[j].items()},
            'tmdb_id'        : doc['tmdb_id'],
            'title'          : doc['title'][:500],
            'text'           : doc['text'][:4096],
            'overview'       : doc['overview'][:3000],
            'genres'         : doc['genres'][:200],
            'genres_list'    : doc['genres_list'][:500],
            'director'       : doc['director'][:500],
            'cast'           : doc['cast'][:1000],
            'year'           : doc['year'],
            'language'       : doc['language'][:10],
            'runtime'        : doc['runtime'],
            'vote_average'   : doc['vote_average'],
            'vote_count'     : doc['vote_count'],
            'audience_count' : doc['audience_count'],
            'poster_path'    : doc['poster_path'][:500],
        })

    collection.insert(data)

collection.flush()
collection.load()
print(f"\n삽입 완료: {collection.num_entities:,}개")
connections.disconnect("default")
print("완료!")