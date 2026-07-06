from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.movie import ReadMovie


class CreateActor(BaseModel):
    # TMDB 인물 ID가 있으면 동명이인 구분 기준으로 사용한다.
    tmdb_actor_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    profile_path: str | None = Field(default=None, max_length=300)


class UpdateActor(BaseModel):
    # TMDB 동기화에서 일부 필드만 갱신할 수 있게 부분 수정을 허용한다.
    tmdb_actor_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    profile_path: str | None = Field(default=None, max_length=300)


class ReadActor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_actor_id: int | None
    name: str
    profile_path: str | None
    created_at: datetime
    updated_at: datetime


class CreateMovieActor(BaseModel):
    # TMDB credits API의 cast 항목을 영화-배우 연결 row로 저장한다.
    movie_id: int
    actor_id: int
    character_name: str | None = Field(default=None, max_length=150)
    cast_order: int | None = None


class ReadMovieActor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int
    actor_id: int
    character_name: str | None
    cast_order: int | None


class ActorMovieRead(ReadMovie):
    # 배우 상세/배우별 영화 모아보기에서 배역명과 출연 순서를 함께 보여준다.
    character_name: str | None = None
    cast_order: int | None = None
