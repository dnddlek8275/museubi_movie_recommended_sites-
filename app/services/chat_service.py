from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.character import Character, CharacterAlias
from app.models.chat import ChatMessage, ChatRoom
from app.models.movie import Movie
from app.models.user import User
from app.schemas.chat import CreateChatMessage, CreateChatRoom


def create_chat_room(db: Session, payload: CreateChatRoom) -> ChatRoom:
    # 채팅방은 사용자에게 종속되므로 user_id 존재 여부를 먼저 확인한다.
    if db.get(User, payload.user_id) is None:
        raise ServiceError("사용자를 찾을 수 없습니다.", status_code=404)

    room = ChatRoom(**payload.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def create_chat_message(db: Session, payload: CreateChatMessage) -> ChatMessage:
    # LLM 추천 JSON이 있으면 저장 전에 tmdb_id 기준 movie_id를 붙인 snapshot으로 정리한다.
    if db.get(ChatRoom, payload.room_id) is None:
        raise ServiceError("채팅방을 찾을 수 없습니다.", status_code=404)

    recommended_movies = None
    if payload.recommended_movies is not None:
        recommended_movies = build_recommended_movies_snapshot_from_llm(db, payload.recommended_movies)

    message = ChatMessage(
        room_id=payload.room_id,
        role=payload.role,
        character_name=payload.character_name,
        content=payload.content,
        recommended_movies=recommended_movies,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def build_recommended_movies_snapshot_from_llm(
    db: Session,
    recommended_movies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # LLM이 제공한 tmdb_id를 내부 movies.id와 매칭하고, 대화 복원용 JSONB snapshot으로 변환한다.
    snapshot: list[dict[str, Any]] = []
    for rank, item in enumerate(recommended_movies, start=1):
        tmdb_id = parse_tmdb_id(item.get("tmdb_id"))
        movie = get_movie_by_tmdb_id(db, tmdb_id) if tmdb_id is not None else None

        snapshot.append(
            {
                "movie_id": movie.id if movie else None,
                "tmdb_id": tmdb_id,
                "title": item.get("title"),
                "year": item.get("year"),
                "genres": item.get("genres"),
                "director": item.get("director"),
                "cast": item.get("cast"),
                "vote_average": item.get("vote_average"),
                "overview": item.get("overview"),
                "poster_url": item.get("poster_url") or item.get("poster_path"),
                "rank": item.get("rank") or rank,
                "reason": item.get("reason"),
                "recommendation_score": item.get("recommendation_score"),
                "matched_preferences": item.get("matched_preferences"),
            }
        )
    return snapshot


def parse_tmdb_id(value: Any) -> int | None:
    # LLM 응답에서는 tmdb_id가 문자열로 올 수 있어 int로 정규화한다.
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceError("tmdb_id는 숫자 형식이어야 합니다.", status_code=400) from exc


def get_movie_by_tmdb_id(db: Session, tmdb_id: int) -> Movie | None:
    # LLM 추천 항목을 내부 영화 row와 연결하기 위해 tmdb_id로 조회한다.
    return db.scalar(select(Movie).where(Movie.tmdb_id == tmdb_id))


def get_character_by_name_or_alias(db: Session, value: str) -> Character | None:
    # /chat/auto에서 사용자 메시지에 나온 정식 이름 또는 별칭을 활성 캐릭터로 매핑한다.
    normalized_value = value.strip()
    if not normalized_value:
        return None

    character = db.scalar(
        select(Character).where(
            Character.name == normalized_value,
            Character.is_active.is_(True),
        )
    )
    if character is not None:
        return character

    return db.scalar(
        select(Character)
        .join(CharacterAlias, CharacterAlias.character_id == Character.id)
        .where(
            CharacterAlias.alias == normalized_value,
            Character.is_active.is_(True),
        )
    )
