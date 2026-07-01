# CineVerse DB/Service Module

이 폴더는 B1 FastAPI 서버에 붙여 사용할 DB 모델, Alembic 마이그레이션, Pydantic 스키마, service 함수를 담당한다.

현재 결정된 흐름:

```text
Frontend -> B1 FastAPI API -> back2 service 함수 -> PostgreSQL
```

따라서 이 폴더에서는 FastAPI 라우터를 제공하지 않는다. 프론트와 통신하는 API 라우터, 응답 포맷, JWT 발급/검증은 B1에서 담당하고, 이 폴더는 DB 작업 함수를 제공한다.

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
python3 -m alembic upgrade head
```

`.env`의 `DATABASE_URL`은 로컬 PostgreSQL 정보에 맞게 수정해야 한다.

## 주요 폴더

| 경로 | 역할 |
| --- | --- |
| `app/core` | DB 설정, 세션, service 예외 |
| `app/models` | SQLAlchemy ORM 모델 |
| `app/schemas` | service 입출력용 Pydantic 스키마 |
| `app/services` | B1에서 직접 호출할 DB/service 함수 |
| `alembic` | DB 마이그레이션 |
| `scripts` | B1 없이 service 동작을 확인하는 실행 스크립트 |

## B1 연결 방식

B1 라우터에서는 HTTP로 back2를 호출하지 않고 service 함수를 직접 import해서 사용한다.

```python
from app.core.database import get_db
from app.core.exceptions import ServiceError
from app.schemas.user import CreateUser
from app.services.user_service import create_user


def register(payload, db):
    try:
        user = create_user(
            db,
            CreateUser(
                email=payload.email,
                password_hash=payload.password_hash,
                nickname=payload.nickname,
            ),
        )
    except ServiceError as exc:
        return {"state": "failure", "message": exc.message}

    return {"state": "success", "message": "요청 처리 성공", "data": {"user_id": user.id}}
```

## Service 예외

service 함수에서 업무 조건 실패가 발생하면 `ServiceError`를 발생시킨다.

```python
from app.core.exceptions import ServiceError
```

B1은 이 예외를 잡아서 팀 응답 규칙에 맞게 `failure` 응답으로 변환하면 된다.

## 주요 service

| service | 주요 함수 |
| --- | --- |
| `user_service.py` | `create_user`, `update_user`, `get_user_by_email`, `get_password_hash_by_email`, `get_user_id_by_email`, `get_nickname_by_email` |
| `auth_service.py` | `create_refresh_token`, `verify_refresh_token`, `revoke_refresh_token` |
| `chat_service.py` | 채팅방/채팅 메시지 저장, LLM 추천 영화 JSON에 `movie_id` 매칭 후 snapshot 저장 |
| `admin_service.py` | 영화/캐릭터 CRUD, 관리자 통계 |
| `interaction_service.py` | 영화 조회/검색 후 조회/좋아요 기록 |
| `movie_search_service.py` | 영화 제목/개요/감독/배우/장르/키워드/언어 검색 |
| `preference_service.py` | 영화/캐릭터 기반 사용자 취향 점수 조회/누적 |
| `recommendation_service.py` | 사용자 취향 점수 기반 영화 추천, 비로그인 추천 placeholder |
| `ranking_service.py` | 인기 영화 랭킹 조회 |
| `user_activity_service.py` | 마이페이지 좋아요/조회 기록 조회 |

## 단독 검증

B1 연결 전에는 아래 스크립트로 DB/service 흐름을 검증한다.

```bash
python scripts/verify_services.py
```

검증 내용:

- 데모 사용자 생성 또는 재사용
- 데모 영화 생성 또는 재사용
- 데모 캐릭터 생성 또는 재사용
- 조회, 검색 후 조회, 좋아요 기록
- 영화 검색 확인
- 취향 점수 누적 확인
- 캐릭터 선택/대화 기반 취향 점수 누적 확인
- 사용자 취향 기반 영화 추천 확인
- 인기 랭킹 집계 확인
- Refresh Token 저장/검증/폐기 확인

실행 전에 마이그레이션이 적용되어 있어야 한다.

```bash
python3 -m alembic upgrade head
```

## 현재 DB 주요 테이블

| 테이블 | 목적 |
| --- | --- |
| `users` | 사용자 기본 정보 |
| `refresh_tokens` | Refresh Token hash 저장/검증/폐기 |
| `movies` | 영화 정보 |
| `movie_genres` | 영화 장르 정규화 테이블 |
| `characters` | 캐릭터 정보/프롬프트 |
| `user_movie_interactions` | 사용자 영화 행동 로그 |
| `user_preference_scores` | 사용자 영화/캐릭터 취향 점수 |
| `movie_stats` | 영화 랭킹 누적 통계 |
| `chat_rooms` | 채팅방 정보 |
| `chat_messages` | 채팅 메시지, 추천 영화 snapshot |
| `admin_audit_logs` | 관리자 작업 이력용 테이블, 현재 로직 미연결 |

## 완료된 범위

- PostgreSQL 스키마/Alembic 마이그레이션
- 영화 장르 정규화 테이블 `movie_genres`
- 사용자 생성/조회 service
- Refresh Token 저장/검증/폐기 service
- 영화/캐릭터 CRUD service
- 영화 조회/검색 후 조회/좋아요 기록 service
- 영화 검색 service
- 영화 인기 랭킹 service
- 영화/캐릭터 기반 취향 점수 누적 service
- 사용자 취향 기반 영화 추천 service
- 마이페이지용 취향/좋아요/조회 기록 조회 service

## 영화 CSV 적재 기준

영화 CSV는 아직 자동 적재하지 않는다. 적재 스크립트를 만들 때는 아래 기준을 따른다.

| CSV 컬럼 | 처리 방식 |
| --- | --- |
| `tmdb_id` | `movies.tmdb_id`에 저장, 중복 판단 기준 |
| `title` | `movies.title`에 저장 |
| `overview` | `movies.overview`에 저장 |
| `genres` | 콤마로 분리해 `movie_genres`에 여러 row로 저장하고, 호환을 위해 `movies.genres`에도 배열로 저장 |
| `director` | `movies.director`에 문자열로 저장 |
| `cast` | 콤마로 분리해 `movies.cast` 배열로 저장 |
| `language` | `movies.language`에 저장 |
| `vote_average` | `movies.vote_average`에 숫자로 저장 |
| `vote_count` | `movies.vote_count`에 숫자로 저장 |
| `audience_count` | `movies.audience_count`에 숫자로 저장 |
| `poster_path` | TMDB 상대경로 그대로 저장 |
| `개봉연도` | 정수 연도로 변환해 `movies.year`에 저장 |
| `search_text` | RDB에서는 사용하지 않으므로 저장하지 않음 |

현재 CSV에는 있지만 아직 DB에 저장하지 않는 컬럼은 `media_type`, `original_title`, `release_date`, `runtime`, `popularity`, `search_text`다. `original_title`, `release_date`, `runtime`, `popularity`는 상세 화면이나 정렬 정책에서 필요해지면 별도 마이그레이션으로 추가한다.

## 남은 범위

- B1 라우터에서 service 직접 호출로 연결
- 영화 CSV import 스크립트 작성
- 비로그인 사용자 식별/JWT 정책 확정 후 guest 추천 로직 구현
- 관리자 작업 이력 저장 로직
- 배포/CI/CD
