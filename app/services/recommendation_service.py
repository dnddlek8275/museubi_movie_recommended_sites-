from collections import defaultdict
from math import log1p

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.character import Character
from app.models.interaction import MovieStats, UserMovieInteraction, UserPreferenceScore
from app.models.movie import Movie
from app.models.user import User
from app.schemas.movie import ReadMovie
from app.schemas.recommendation import RecommendedMovieRead
from app.services.preference_service import get_movie_actor_names, get_movie_genre_values, normalize_values

PREFERENCE_WEIGHT = {
    # 취향 타입마다 영화 선택에 주는 영향이 달라 가중치를 분리한다.
    "genre": 1.2,
    "actor": 1.0,
    "director": 1.1,
    "keyword": 0.9,
    "language": 0.5,
    "character": 1.3,
}


def recommend_movies_for_user(
    db: Session,
    user_id: int,
    *,
    limit: int = 20,
    exclude_interacted: bool = True,
) -> list[dict]:
    # 사용자 취향 점수와 영화 메타데이터를 비교해 추천 영화 목록을 만든다.
    if db.get(User, user_id) is None:
        raise ServiceError("사용자를 찾을 수 없습니다.", status_code=404)

    preferences = list_user_recommendation_preferences(db, user_id)
    excluded_movie_ids = get_interacted_movie_ids(db, user_id) if exclude_interacted else set()
    movies = list_candidate_movies(db, excluded_movie_ids=excluded_movie_ids)

    if not preferences:
        return recommend_popular_movies(db, limit=limit, excluded_movie_ids=excluded_movie_ids)

    character_names_by_movie_id = list_character_names_by_movie_id(db)
    recommendations = [
        build_recommendation(movie, preferences, character_names_by_movie_id.get(movie.id, []))
        for movie in movies
    ]
    recommendations = [recommendation for recommendation in recommendations if recommendation["recommendation_score"] > 0]
    recommendations.sort(key=lambda item: item["recommendation_score"], reverse=True)

    if recommendations:
        return recommendations[:limit]
    return recommend_popular_movies(db, limit=limit, excluded_movie_ids=excluded_movie_ids)


def recommend_movies_for_guest(db: Session, *, limit: int = 20) -> list[dict]:
    # 비로그인 식별 방식이 확정되기 전까지는 개인 취향 저장 없이 인기 기반 추천만 고려한다.
    raise ServiceError("비로그인 추천 정책은 아직 확정되지 않았습니다.", status_code=501)


def list_user_recommendation_preferences(db: Session, user_id: int) -> list[UserPreferenceScore]:
    # 추천 계산에 사용할 사용자 취향 점수를 높은 순서로 조회한다.
    stmt = (
        select(UserPreferenceScore)
        .where(UserPreferenceScore.user_id == user_id)
        .order_by(UserPreferenceScore.score.desc())
    )
    return list(db.scalars(stmt).all())


def get_interacted_movie_ids(db: Session, user_id: int) -> set[int]:
    # 이미 반응한 영화는 기본 추천에서 제외해 새 영화를 보여준다.
    stmt = select(UserMovieInteraction.movie_id).where(UserMovieInteraction.user_id == user_id)
    return set(db.scalars(stmt).all())


def list_candidate_movies(db: Session, *, excluded_movie_ids: set[int]) -> list[Movie]:
    # 현재 보유한 영화 전체를 후보로 두고 Python 점수 계산에서 취향 매칭을 처리한다.
    stmt = select(Movie).order_by(Movie.id.desc())
    if excluded_movie_ids:
        stmt = stmt.where(Movie.id.not_in(excluded_movie_ids))
    return list(db.scalars(stmt).all())


def list_character_names_by_movie_id(db: Session) -> dict[int, list[str]]:
    # character 취향 점수를 영화 추천에 반영하기 위해 영화별 캐릭터명을 모은다.
    character_names_by_movie_id: dict[int, list[str]] = defaultdict(list)
    stmt = select(Character.movie_id, Character.name).where(Character.movie_id.is_not(None))
    for movie_id, name in db.execute(stmt):
        character_names_by_movie_id[movie_id].append(name)
    return dict(character_names_by_movie_id)


def build_recommendation(
    movie: Movie,
    preferences: list[UserPreferenceScore],
    character_names: list[str],
) -> dict:
    # 영화 하나에 대해 취향 매칭 점수와 추천 사유를 계산한다.
    movie_items = collect_recommendation_items(movie, character_names)
    matched_preferences: list[str] = []
    score = 0.0

    for preference in preferences:
        preference_key = (preference.preference_type, preference.preference_value)
        if preference_key not in movie_items:
            continue

        weight = PREFERENCE_WEIGHT.get(preference.preference_type, 1.0)
        score += preference.score * weight
        matched_preferences.append(f"{preference.preference_type}:{preference.preference_value}")

    score += calculate_popularity_boost(movie)
    return RecommendedMovieRead(
        movie=ReadMovie.model_validate(movie),
        recommendation_score=round(score, 3),
        matched_preferences=matched_preferences,
    ).model_dump()


def collect_recommendation_items(movie: Movie, character_names: list[str]) -> set[tuple[str, str]]:
    # 영화 메타데이터를 사용자 취향 점수와 비교 가능한 key 집합으로 변환한다.
    items: set[tuple[str, str]] = set()
    items.update(("genre", value) for value in get_movie_genre_values(movie))
    items.update(("actor", value) for value in get_movie_actor_names(movie))
    items.update(("keyword", value) for value in normalize_values(movie.keywords))
    items.update(("character", value) for value in normalize_values(character_names))
    if movie.director:
        items.add(("director", movie.director.strip()))
    if movie.language:
        items.add(("language", movie.language.strip()))
    return {(item_type, item_value) for item_type, item_value in items if item_value}


def calculate_popularity_boost(movie: Movie) -> float:
    # 취향 점수가 같은 영화끼리는 평점/관객수 기반으로 약하게 순서를 보정한다.
    vote_boost = (movie.vote_average or 0) * 0.05
    audience_boost = log1p(movie.audience_count or 0) * 0.02
    return vote_boost + audience_boost


def recommend_popular_movies(
    db: Session,
    *,
    limit: int,
    excluded_movie_ids: set[int],
) -> list[dict]:
    # 취향 데이터가 없거나 매칭 결과가 없을 때 인기 영화 기반 추천으로 대체한다.
    stmt = (
        select(Movie)
        .outerjoin(MovieStats, MovieStats.movie_id == Movie.id)
        .order_by(
            MovieStats.ranking_score.desc().nullslast(),
            Movie.vote_average.desc().nullslast(),
            Movie.audience_count.desc().nullslast(),
            Movie.id.desc(),
        )
        .limit(limit)
    )
    if excluded_movie_ids:
        stmt = stmt.where(Movie.id.not_in(excluded_movie_ids))

    return [
        RecommendedMovieRead(
            movie=ReadMovie.model_validate(movie),
            recommendation_score=round(calculate_popularity_boost(movie), 3),
            matched_preferences=[],
        ).model_dump()
        for movie in db.scalars(stmt)
    ]
