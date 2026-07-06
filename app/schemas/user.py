from pydantic import BaseModel, ConfigDict, EmailStr


class CreateUser(BaseModel):
    email: EmailStr
    password_hash: str
    nickname: str
    profile_image: str | None = None
    preferred_genres: list[str] | None = None
    preferred_actors: list[str] | None = None
    preferred_keywords: list[str] | None = None
    is_admin: bool = False


class UpdateUser(BaseModel):
    password_hash: str | None = None
    nickname: str | None = None
    profile_image: str | None = None
    preferred_genres: list[str] | None = None
    preferred_actors: list[str] | None = None
    preferred_keywords: list[str] | None = None
    is_admin: bool | None = None


class ReadUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    nickname: str
    profile_image: str | None
    preferred_genres: list[str] | None
    preferred_actors: list[str] | None
    preferred_keywords: list[str] | None
    is_admin: bool
