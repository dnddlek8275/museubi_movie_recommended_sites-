from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Movie(TimestampMixin, Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    genres: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    director: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cast: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 삭제 처리는 DB의 ON DELETE CASCADE에 맡겨 ORM이 FK를 NULL로 바꾸지 않게 한다.
    interactions = relationship("UserMovieInteraction", back_populates="movie", passive_deletes=True)
    stats = relationship("MovieStats", back_populates="movie", passive_deletes=True, uselist=False)
    genre_rows = relationship(
        "MovieGenre",
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MovieGenre(Base):
    __tablename__ = "movie_genres"
    __table_args__ = (
        UniqueConstraint("movie_id", "genre", name="uq_movie_genres_movie_genre"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    genre: Mapped[str] = mapped_column(String(50), index=True, nullable=False)

    # 장르 검색/추천은 별도 테이블을 기준으로 하지만 Movie에서 쉽게 접근하도록 관계를 둔다.
    movie = relationship("Movie", back_populates="genre_rows")
