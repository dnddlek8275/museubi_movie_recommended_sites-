from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.movie import ReadMovie


class CreateDailyAiRecommendation(BaseModel):
    # AI가 하루 단위로 생성한 한 문장과 추천 영화 목록을 저장한다.
    recommend_date: date
    answer: str = Field(min_length=1)
    movie_ids: list[int] = Field(min_length=1, max_length=3)


class ReadDailyAiRecommendationMovie(BaseModel):
    movie: ReadMovie
    display_order: int


class ReadDailyAiRecommendation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommend_date: date
    answer: str
    movies: list[ReadDailyAiRecommendationMovie]
    created_at: datetime
