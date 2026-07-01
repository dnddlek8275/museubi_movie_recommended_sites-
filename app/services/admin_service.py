from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.character import Character
from app.models.interaction import UserMovieInteraction
from app.models.movie import Movie, MovieGenre
from app.models.user import User
from app.schemas.character import CreateCharacter, UpdateCharacter
from app.schemas.movie import CreateMovie, UpdateMovie
from app.services.ranking_service import list_top_movies


def get_admin_stats(db: Session) -> dict:
    # 관리자 화면에 표시할 주요 테이블 집계 정보를 만든다.
    return {
        "user_count": db.scalar(select(func.count(User.id))) or 0,
        "movie_count": db.scalar(select(func.count(Movie.id))) or 0,
        "character_count": db.scalar(select(func.count(Character.id))) or 0,
        "interaction_count": db.scalar(select(func.count(UserMovieInteraction.id))) or 0,
        "top_movies": list_top_movies(db, limit=10),
    }


def list_movies(db: Session, skip: int = 0, limit: int = 50) -> list[Movie]:
    # 영화 목록을 최신 등록 순서로 페이지 조회한다.
    stmt = select(Movie).order_by(Movie.id.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def get_movie_or_404(db: Session, movie_id: int) -> Movie:
    # 영화 ID로 영화를 조회하고 없으면 404 예외를 발생시킨다.
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise ServiceError("영화를 찾을 수 없습니다.", status_code=404)
    return movie


def create_movie(db: Session, payload: CreateMovie) -> Movie:
    # 관리자 입력값으로 새 영화 row를 생성한다.
    movie_data = payload.model_dump()
    genres = movie_data.pop("genres", None)
    movie = Movie(**movie_data, genres=genres)
    sync_movie_genres(movie, genres)
    db.add(movie)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # tmdb_id는 외부 데이터 동기화 기준이라 중복을 명확한 409로 돌려준다.
        raise ServiceError("이미 존재하는 TMDB ID입니다.", status_code=409) from exc
    db.refresh(movie)
    return movie


def update_movie(db: Session, movie_id: int, payload: UpdateMovie) -> Movie:
    # 선택적으로 전달된 필드만 사용해 영화 정보를 수정한다.
    movie = get_movie_or_404(db, movie_id)
    update_data = payload.model_dump(exclude_unset=True)
    genres_was_sent = "genres" in update_data
    genres = update_data.pop("genres", None)
    for field, value in update_data.items():
        setattr(movie, field, value)
    if genres_was_sent:
        movie.genres = genres
        sync_movie_genres(movie, genres)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError("이미 존재하는 TMDB ID입니다.", status_code=409) from exc
    db.refresh(movie)
    return movie


def delete_movie(db: Session, movie_id: int) -> None:
    # 영화 ID로 영화를 찾아 삭제한다.
    movie = get_movie_or_404(db, movie_id)
    db.delete(movie)
    db.commit()


def sync_movie_genres(movie: Movie, genres: list[str] | None) -> None:
    # movies.genres와 movie_genres가 서로 다른 값을 갖지 않도록 저장 시점에 함께 갱신한다.
    movie.genre_rows = [
        MovieGenre(genre=genre)
        for genre in normalize_movie_genres(genres)
    ]


def normalize_movie_genres(genres: list[str] | None) -> list[str]:
    # CSV/API 입력에서 공백과 중복 장르를 제거해 movie_genres에 저장할 값을 만든다.
    normalized: list[str] = []
    seen: set[str] = set()
    for genre in genres or []:
        value = genre.strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def validate_movie_id(db: Session, movie_id: int | None) -> None:
    # 캐릭터가 연결하려는 영화 ID가 실제 존재하는지 확인한다.
    # 캐릭터가 존재하지 않는 영화에 연결되면 관리자 화면에서 출처 추적이 어려워진다.
    if movie_id is not None and db.get(Movie, movie_id) is None:
        raise ServiceError("연결할 영화를 찾을 수 없습니다.", status_code=404)


def list_characters(db: Session, skip: int = 0, limit: int = 50) -> list[Character]:
    # 캐릭터 목록을 최신 등록 순서로 페이지 조회한다.
    stmt = select(Character).order_by(Character.id.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def get_character_or_404(db: Session, character_id: int) -> Character:
    # 캐릭터 ID로 캐릭터를 조회하고 없으면 404 예외를 발생시킨다.
    character = db.get(Character, character_id)
    if character is None:
        raise ServiceError("캐릭터를 찾을 수 없습니다.", status_code=404)
    return character


def create_character(db: Session, payload: CreateCharacter) -> Character:
    # 관리자 입력값으로 새 캐릭터 row를 생성한다.
    validate_movie_id(db, payload.movie_id)
    character = Character(**payload.model_dump())
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def update_character(db: Session, character_id: int, payload: UpdateCharacter) -> Character:
    # 선택적으로 전달된 필드만 사용해 캐릭터 정보를 수정한다.
    character = get_character_or_404(db, character_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "movie_id" in update_data:
        validate_movie_id(db, update_data["movie_id"])
    for field, value in update_data.items():
        setattr(character, field, value)
    db.commit()
    db.refresh(character)
    return character


def delete_character(db: Session, character_id: int) -> None:
    # 캐릭터 ID로 캐릭터를 찾아 삭제한다.
    character = get_character_or_404(db, character_id)
    db.delete(character)
    db.commit()
