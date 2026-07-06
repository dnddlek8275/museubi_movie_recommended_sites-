from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.actor import Actor, MovieActor
from app.models.movie import Movie
from app.schemas.actor import ActorMovieRead, CreateActor, CreateMovieActor, UpdateActor
from app.schemas.movie import ReadMovie


def list_actors(db: Session, *, skip: int = 0, limit: int = 50) -> list[Actor]:
    # 배우 선택 UI와 관리자 확인용으로 배우 목록을 이름순으로 조회한다.
    stmt = select(Actor).order_by(Actor.name.asc(), Actor.id.asc()).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def get_actor_or_404(db: Session, actor_id: int) -> Actor:
    # 내부 actor_id 기준으로 배우 존재 여부를 확인한다.
    actor = db.get(Actor, actor_id)
    if actor is None:
        raise ServiceError("배우를 찾을 수 없습니다.", status_code=404)
    return actor


def get_actor_by_tmdb_id(db: Session, tmdb_actor_id: int) -> Actor | None:
    # TMDB credits 동기화에서 기존 배우 row 재사용 여부를 판단한다.
    return db.scalar(select(Actor).where(Actor.tmdb_actor_id == tmdb_actor_id))


def create_actor(db: Session, payload: CreateActor) -> Actor:
    # TMDB 또는 관리자 입력값으로 배우 row를 생성한다.
    actor = Actor(**payload.model_dump())
    db.add(actor)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError("이미 존재하는 TMDB 배우 ID입니다.", status_code=409) from exc
    db.refresh(actor)
    return actor


def update_actor(db: Session, actor_id: int, payload: UpdateActor) -> Actor:
    # TMDB 재동기화나 관리자 수정에서 전달된 배우 필드만 갱신한다.
    actor = get_actor_or_404(db, actor_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(actor, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError("이미 존재하는 TMDB 배우 ID입니다.", status_code=409) from exc
    db.refresh(actor)
    return actor


def upsert_actor_from_tmdb(db: Session, payload: CreateActor) -> Actor:
    # TMDB person id가 있으면 기존 row를 갱신하고, 없으면 새 배우 row를 만든다.
    if payload.tmdb_actor_id is None:
        return create_actor(db, payload)

    actor = get_actor_by_tmdb_id(db, payload.tmdb_actor_id)
    if actor is None:
        return create_actor(db, payload)

    actor.name = payload.name
    actor.profile_path = payload.profile_path
    db.commit()
    db.refresh(actor)
    return actor


def link_movie_actor(db: Session, payload: CreateMovieActor) -> MovieActor:
    # 영화와 배우를 연결해 배우별 영화 모아보기와 영화별 출연진 조회를 가능하게 한다.
    if db.get(Movie, payload.movie_id) is None:
        raise ServiceError("영화를 찾을 수 없습니다.", status_code=404)
    if db.get(Actor, payload.actor_id) is None:
        raise ServiceError("배우를 찾을 수 없습니다.", status_code=404)

    movie_actor = db.scalar(
        select(MovieActor).where(
            MovieActor.movie_id == payload.movie_id,
            MovieActor.actor_id == payload.actor_id,
        )
    )
    if movie_actor is None:
        movie_actor = MovieActor(**payload.model_dump())
        db.add(movie_actor)
    else:
        movie_actor.character_name = payload.character_name
        movie_actor.cast_order = payload.cast_order

    db.commit()
    db.refresh(movie_actor)
    return movie_actor


def list_movies_by_actor(db: Session, actor_id: int, *, skip: int = 0, limit: int = 50) -> list[dict]:
    # 배우 상세 화면에서 해당 배우가 출연한 내부 보유 영화를 조회한다.
    get_actor_or_404(db, actor_id)
    stmt = (
        select(Movie, MovieActor.character_name, MovieActor.cast_order)
        .join(MovieActor, MovieActor.movie_id == Movie.id)
        .where(MovieActor.actor_id == actor_id)
        .order_by(Movie.year.desc().nullslast(), Movie.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [
        ActorMovieRead(
            **ReadMovie.model_validate(movie).model_dump(),
            character_name=character_name,
            cast_order=cast_order,
        ).model_dump()
        for movie, character_name, cast_order in db.execute(stmt)
    ]
