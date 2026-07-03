from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateCharacter(BaseModel):
    # 캐릭터는 영화 연결 없이도 먼저 등록할 수 있어 movie_id를 선택값으로 둔다.
    movie_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] | None = None
    movie_title: str = Field(min_length=1, max_length=200)
    actor: str | None = Field(default=None, max_length=100)
    lang: str = Field(min_length=1, max_length=10)
    system_prompt: str = Field(min_length=1)
    profile_image: str | None = Field(default=None, max_length=300)
    is_active: bool = True


class UpdateCharacter(BaseModel):
    # 관리자 화면에서 일부 필드만 수정할 수 있도록 부분 수정 형태를 허용한다.
    movie_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    aliases: list[str] | None = None
    movie_title: str | None = Field(default=None, min_length=1, max_length=200)
    actor: str | None = Field(default=None, max_length=100)
    lang: str | None = Field(default=None, min_length=1, max_length=10)
    system_prompt: str | None = Field(default=None, min_length=1)
    profile_image: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None


class ReadCharacter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int | None
    name: str
    aliases: list[str]
    movie_title: str
    actor: str | None
    lang: str
    system_prompt: str
    profile_image: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
