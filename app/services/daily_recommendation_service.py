from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.daily_recommendation import DailyAiRecommendation, DailyAiRecommendationMovie
from app.models.movie import Movie
from app.schemas.daily_recommendation import CreateDailyAiRecommendation, ReadDailyAiRecommendation, ReadDailyAiRecommendationMovie
from app.schemas.movie import ReadMovie


def create_daily_ai_recommendation(db: Session, payload: CreateDailyAiRecommendation) -> dict:
    # 하루 추천 묶음을 새로 생성하고 추천 영화 순서를 함께 저장한다.
    validate_daily_movie_ids(db, payload.movie_ids)
    daily_recommendation = DailyAiRecommendation(
        recommend_date=payload.recommend_date,
        answer=payload.answer,
    )
    sync_daily_recommendation_movies(daily_recommendation, payload.movie_ids)
    db.add(daily_recommendation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError("이미 해당 날짜의 AI 추천이 존재합니다.", status_code=409) from exc
    db.refresh(daily_recommendation)
    return build_daily_recommendation_response(daily_recommendation)


def replace_daily_ai_recommendation(db: Session, payload: CreateDailyAiRecommendation) -> dict:
    # 같은 날짜 추천이 있으면 문장과 영화 목록을 교체하고, 없으면 새로 만든다.
    validate_daily_movie_ids(db, payload.movie_ids)
    daily_recommendation = get_daily_ai_recommendation_model_by_date(db, payload.recommend_date)
    if daily_recommendation is None:
        return create_daily_ai_recommendation(db, payload)

    daily_recommendation.answer = payload.answer
    daily_recommendation.movie_rows = []
    db.flush()
    sync_daily_recommendation_movies(daily_recommendation, payload.movie_ids)
    db.commit()
    db.refresh(daily_recommendation)
    return build_daily_recommendation_response(daily_recommendation)


def get_daily_ai_recommendation_by_date(db: Session, recommend_date: date) -> dict:
    # 날짜 기준으로 데일리 AI 추천 묶음과 영화 카드 목록을 조회한다.
    daily_recommendation = get_daily_ai_recommendation_model_by_date(db, recommend_date)
    if daily_recommendation is None:
        raise ServiceError("해당 날짜의 AI 추천을 찾을 수 없습니다.", status_code=404)
    return build_daily_recommendation_response(daily_recommendation)


def get_daily_ai_recommendation_model_by_date(db: Session, recommend_date: date) -> DailyAiRecommendation | None:
    # recommend_date는 하루 한 묶음만 존재하므로 단건 조회 기준으로 사용한다.
    return db.scalar(
        select(DailyAiRecommendation).where(DailyAiRecommendation.recommend_date == recommend_date)
    )


def validate_daily_movie_ids(db: Session, movie_ids: list[int]) -> None:
    # 화면은 최대 3개 카드만 보여주므로 추천 영화 개수와 중복, 존재 여부를 저장 전에 확인한다.
    if not 1 <= len(movie_ids) <= 3:
        raise ServiceError("데일리 추천 영화는 1개 이상 3개 이하만 저장할 수 있습니다.", status_code=400)
    if len(movie_ids) != len(set(movie_ids)):
        raise ServiceError("데일리 추천 영화가 중복되었습니다.", status_code=400)

    existing_ids = set(db.scalars(select(Movie.id).where(Movie.id.in_(movie_ids))).all())
    missing_ids = set(movie_ids) - existing_ids
    if missing_ids:
        raise ServiceError("존재하지 않는 추천 영화가 포함되어 있습니다.", status_code=404)


def sync_daily_recommendation_movies(daily_recommendation: DailyAiRecommendation, movie_ids: list[int]) -> None:
    # 배열 순서를 display_order로 고정해 DB 조회 시 카드 순서를 안정적으로 복원한다.
    daily_recommendation.movie_rows = [
        DailyAiRecommendationMovie(movie_id=movie_id, display_order=index)
        for index, movie_id in enumerate(movie_ids, start=1)
    ]


def build_daily_recommendation_response(daily_recommendation: DailyAiRecommendation) -> dict:
    # DB 모델을 B1이 바로 응답 data에 넣기 쉬운 dict 형태로 변환한다.
    movie_rows = sorted(daily_recommendation.movie_rows, key=lambda row: row.display_order)
    return ReadDailyAiRecommendation(
        id=daily_recommendation.id,
        recommend_date=daily_recommendation.recommend_date,
        answer=daily_recommendation.answer,
        created_at=daily_recommendation.created_at,
        movies=[
            ReadDailyAiRecommendationMovie(
                movie=ReadMovie.model_validate(row.movie),
                display_order=row.display_order,
            )
            for row in movie_rows
        ],
    ).model_dump()
