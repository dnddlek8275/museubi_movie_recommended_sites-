from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateChatRoom(BaseModel):
    user_id: int
    room_type: str = Field(pattern="^(general|character|group)$")
    characters: list[str] | None = None


class CreateChatMessage(BaseModel):
    room_id: int
    role: str = Field(pattern="^(user|assistant)$")
    content: str
    character_name: str | None = None
    recommended_movies: list[dict[str, Any]] | None = None


class ReadChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    role: str
    character_name: str | None
    content: str
    recommended_movies: list[dict[str, Any]] | None
    created_at: datetime

