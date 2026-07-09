from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DailyAiRecommendation(Base):
    __tablename__ = "daily_ai_recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recommend_date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 오늘의 한 문장 묶음이 삭제되면 추천 영화 연결도 함께 제거한다.
    movie_rows = relationship(
        "DailyAiRecommendationMovie",
        back_populates="daily_recommendation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DailyAiRecommendationMovie(Base):
    __tablename__ = "daily_ai_recommendation_movies"
    __table_args__ = (
        UniqueConstraint("daily_recommendation_id", "display_order", name="uq_daily_ai_recommendation_movies_order"),
        CheckConstraint("display_order BETWEEN 1 AND 3", name="ck_daily_ai_recommendation_movies_display_order"),
    )

    daily_recommendation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("daily_ai_recommendations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    movie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # 추천 묶음과 실제 영화 row를 연결해 화면에서는 movies 데이터를 조인해서 사용한다.
    daily_recommendation = relationship("DailyAiRecommendation", back_populates="movie_rows")
    movie = relationship("Movie")
