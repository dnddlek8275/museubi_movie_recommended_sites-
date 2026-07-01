from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.movie import Movie, MovieGenre
from app.schemas.movie import ReadMovie
from app.schemas.search import MovieSearchResultRead
from app.services.preference_service import get_movie_genre_values, normalize_values

SEARCH_FIELD_WEIGHT = {
    # 제목 매칭이 사용자의 의도와 가장 가까워 가장 높은 가중치를 준다.
    "title": 5.0,
    "director": 3.0,
    "cast": 2.5,
    "genre": 2.0,
    "keyword": 1.8,
    "overview": 1.0,
    "language": 0.5,
}


def search_movies(db: Session, query: str, *, limit: int = 20, skip: int = 0) -> list[dict]:
    # 영화 제목/개요/감독/배우/장르/키워드/언어를 대상으로 검색한다.
    normalized_query = normalize_search_query(query)
    if not normalized_query:
        raise ServiceError("검색어를 입력해야 합니다.", status_code=400)

    movies = list_search_candidate_movies(db, normalized_query, limit=limit, skip=skip)
    results = [build_search_result(movie, normalized_query) for movie in movies]
    results.sort(key=lambda item: item["search_score"], reverse=True)
    return results


def normalize_search_query(query: str) -> str:
    # 검색어 앞뒤 공백을 제거하고 대소문자 차이를 없앤다.
    return query.strip().lower()


def list_search_candidate_movies(db: Session, query: str, *, limit: int, skip: int) -> list[Movie]:
    # DB에서 1차 후보를 줄인 뒤 Python에서 필드별 점수를 계산한다.
    pattern = f"%{query}%"
    stmt = (
        select(Movie)
        .where(
            or_(
                Movie.title.ilike(pattern),
                Movie.overview.ilike(pattern),
                Movie.director.ilike(pattern),
                Movie.language.ilike(pattern),
                Movie.id.in_(select(MovieGenre.movie_id).where(MovieGenre.genre.ilike(pattern))),
                func.array_to_string(Movie.cast, " ").ilike(pattern),
                func.array_to_string(Movie.keywords, " ").ilike(pattern),
            )
        )
        .order_by(Movie.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def build_search_result(movie: Movie, query: str) -> dict:
    # 검색 후보 영화 하나에 대해 매칭 필드와 검색 점수를 계산한다.
    matched_fields: list[str] = []
    search_score = 0.0

    for field_name, matched in collect_search_matches(movie, query):
        if not matched:
            continue
        matched_fields.append(field_name)
        search_score += SEARCH_FIELD_WEIGHT[field_name]

    return MovieSearchResultRead(
        **ReadMovie.model_validate(movie).model_dump(),
        search_score=round(search_score, 3),
        matched_fields=matched_fields,
    ).model_dump()


def collect_search_matches(movie: Movie, query: str) -> list[tuple[str, bool]]:
    # 영화의 각 검색 대상 필드가 검색어와 매칭되는지 확인한다.
    return [
        ("title", contains_text(movie.title, query)),
        ("overview", contains_text(movie.overview, query)),
        ("director", contains_text(movie.director, query)),
        ("language", contains_text(movie.language, query)),
        ("genre", contains_any(get_movie_genre_values(movie), query)),
        ("cast", contains_any(movie.cast, query)),
        ("keyword", contains_any(movie.keywords, query)),
    ]


def contains_text(value: str | None, query: str) -> bool:
    # 단일 문자열 필드가 검색어를 포함하는지 확인한다.
    return bool(value and query in value.lower())


def contains_any(values: list[str] | None, query: str) -> bool:
    # 배열형 문자열 필드 중 검색어를 포함하는 값이 있는지 확인한다.
    return any(query in value.lower() for value in normalize_values(values))
