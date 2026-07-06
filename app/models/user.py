from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    profile_image: Mapped[str | None] = mapped_column(String(300), nullable=True)
    preferred_genres: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_actors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    # 사용자 삭제 시 행동/취향 데이터는 DB cascade로 정리되게 둔다.
    interactions = relationship("UserMovieInteraction", back_populates="user", passive_deletes=True)
    preference_scores = relationship("UserPreferenceScore", back_populates="user", passive_deletes=True)
    refresh_tokens = relationship("RefreshToken", back_populates="user", passive_deletes=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Refresh Token은 사용자 계정에 종속되므로 사용자 삭제 시 함께 정리한다.
    user = relationship("User", back_populates="refresh_tokens")
