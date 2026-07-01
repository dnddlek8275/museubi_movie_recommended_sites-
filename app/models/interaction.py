from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class UserMovieInteraction(Base):
    __tablename__ = "user_movie_interactions"
    # 기획에서 제외된 bookmark/dislike는 저장하지 않고, 실제 점수에 쓰는 행동만 허용한다.
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('view', 'search_click', 'like')",
            name="ck_user_movie_interactions_action_type",
        ),
        CheckConstraint(
            "source IN ('direct', 'search', 'recommend', 'ranking', 'admin', 'unknown')",
            name="ck_user_movie_interactions_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    movie_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("movies.id", ondelete="CASCADE"), index=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="interactions")
    movie = relationship("Movie", back_populates="interactions")


class UserPreferenceScore(TimestampMixin, Base):
    __tablename__ = "user_preference_scores"
    # 같은 사용자에게 같은 취향값은 한 row만 두고 score를 누적한다.
    __table_args__ = (
        CheckConstraint(
            "preference_type IN ('genre', 'actor', 'director', 'keyword', 'language', 'character')",
            name="ck_user_preference_scores_preference_type",
        ),
        UniqueConstraint("user_id", "preference_type", "preference_value", name="uq_user_preference_scores_value"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    preference_type: Mapped[str] = mapped_column(String(20), nullable=False)
    preference_value: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)

    user = relationship("User", back_populates="preference_scores")


class MovieStats(TimestampMixin, Base):
    __tablename__ = "movie_stats"

    movie_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    search_click_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    ranking_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    movie = relationship("Movie", back_populates="stats")
