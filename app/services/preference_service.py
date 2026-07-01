from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.character import Character
from app.models.interaction import UserPreferenceScore
from app.models.movie import Movie
from app.models.user import User

PREFERENCE_SCORE = {
    # 취향 점수는 개인 선호 강도 기준이라 랭킹 점수보다 세밀하게 둔다.
    "view": 0.5,
    "search_click": 0.8,
    "like": 2.0,
}

CHARACTER_PREFERENCE_SCORE = {
    # 캐릭터는 시청 완료 개념이 없으므로 선택/대화처럼 명확한 관심 행동만 반영한다.
    "select": 0.8,
    "chat": 1.0,
}


def list_user_preference_scores(
    db: Session,
    user_id: int,
    *,
    preference_type: str | None = None,
    limit: int = 20,
) -> list[UserPreferenceScore]:
    # 사용자별 취향 점수를 조건에 맞게 조회한다.
    if db.get(User, user_id) is None:
        raise ServiceError("사용자를 찾을 수 없습니다.", status_code=404)

    stmt = (
        select(UserPreferenceScore)
        .where(UserPreferenceScore.user_id == user_id)
    )
    if preference_type is not None:
        stmt = stmt.where(UserPreferenceScore.preference_type == preference_type)
    stmt = stmt.order_by(UserPreferenceScore.score.desc(), UserPreferenceScore.preference_value.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def update_user_preference_scores(
    db: Session,
    *,
    user_id: int,
    movie: Movie,
    action_type: str,
) -> None:
    # 영화 행동을 사용자 취향 축별 점수로 변환해 누적한다.
    score_delta = PREFERENCE_SCORE[action_type]
    preference_items = collect_movie_preference_items(movie)

    for preference_type, preference_value in preference_items:
        apply_preference_score(
            db,
            user_id=user_id,
            preference_type=preference_type,
            preference_value=preference_value,
            score_delta=score_delta,
        )


def update_user_character_preference_score(
    db: Session,
    *,
    user_id: int,
    character_id: int,
    action_type: str,
) -> UserPreferenceScore:
    # 캐릭터 선택/대화 행동을 character 취향 점수로 누적한다.
    if db.get(User, user_id) is None:
        raise ServiceError("사용자를 찾을 수 없습니다.", status_code=404)

    character = db.get(Character, character_id)
    if character is None:
        raise ServiceError("캐릭터를 찾을 수 없습니다.", status_code=404)
    if action_type not in CHARACTER_PREFERENCE_SCORE:
        raise ServiceError("지원하지 않는 캐릭터 취향 행동입니다.", status_code=400)

    score_delta = CHARACTER_PREFERENCE_SCORE[action_type]
    apply_preference_score(
        db,
        user_id=user_id,
        preference_type="character",
        preference_value=character.name,
        score_delta=score_delta,
    )
    db.commit()
    return get_preference_score_or_404(
        db,
        user_id=user_id,
        preference_type="character",
        preference_value=character.name,
    )


def apply_preference_score(
    db: Session,
    *,
    user_id: int,
    preference_type: str,
    preference_value: str,
    score_delta: float,
) -> None:
    # 같은 취향값은 row를 늘리지 않고 점수만 누적해 추천 조회를 단순하게 만든다.
    stmt = insert(UserPreferenceScore).values(
        user_id=user_id,
        preference_type=preference_type,
        preference_value=preference_value,
        score=score_delta,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_preference_scores_value",
        set_={
            "score": UserPreferenceScore.score + score_delta,
        },
    )
    db.execute(stmt)


def get_preference_score_or_404(
    db: Session,
    *,
    user_id: int,
    preference_type: str,
    preference_value: str,
) -> UserPreferenceScore:
    # 방금 갱신한 취향 점수 row를 조회해 호출자에게 반환한다.
    preference = db.scalar(
        select(UserPreferenceScore).where(
            UserPreferenceScore.user_id == user_id,
            UserPreferenceScore.preference_type == preference_type,
            UserPreferenceScore.preference_value == preference_value,
        )
    )
    if preference is None:
        raise ServiceError("취향 점수를 찾을 수 없습니다.", status_code=404)
    return preference


def collect_movie_preference_items(movie: Movie) -> list[tuple[str, str]]:
    # 영화 메타데이터에서 취향 점수로 저장할 항목 목록을 만든다.
    # 영화 메타데이터를 취향 축으로 바꿔 저장하면 추천 로직이 테이블 하나만 조회하면 된다.
    items: list[tuple[str, str]] = []
    items.extend(("genre", value) for value in get_movie_genre_values(movie))
    items.extend(("actor", value) for value in normalize_values(movie.cast))
    items.extend(("keyword", value) for value in normalize_values(movie.keywords))
    if movie.director:
        items.append(("director", movie.director.strip()))
    if movie.language:
        items.append(("language", movie.language.strip()))
    return [(item_type, item_value) for item_type, item_value in items if item_value]


def normalize_values(values: list[str] | None) -> list[str]:
    # 배열형 문자열 값에서 빈 값을 제거하고 앞뒤 공백을 정리한다.
    if not values:
        return []
    return [value.strip() for value in values if value and value.strip()]


def get_movie_genre_values(movie: Movie) -> list[str]:
    # 장르는 정규화 테이블을 우선 사용하고, 기존 배열 컬럼은 이전 데이터 호환용으로만 사용한다.
    genre_rows = getattr(movie, "genre_rows", None)
    if genre_rows:
        return normalize_values([row.genre for row in genre_rows])
    return normalize_values(movie.genres)
