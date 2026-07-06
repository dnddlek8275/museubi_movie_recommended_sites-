from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Actor(TimestampMixin, Base):
    __tablename__ = "actors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tmdb_actor_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    profile_path: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # 배우 삭제 시 영화-배우 연결도 함께 정리한다.
    movie_rows = relationship("MovieActor", back_populates="actor", cascade="all, delete-orphan", passive_deletes=True)


class MovieActor(Base):
    __tablename__ = "movie_actors"
    __table_args__ = (
        UniqueConstraint("movie_id", "actor_id", name="uq_movie_actors_movie_actor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("actors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    character_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    cast_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 배우별 영화 모아보기와 영화별 출연진 조회를 위해 양쪽 관계를 둔다.
    movie = relationship("Movie", back_populates="actor_rows")
    actor = relationship("Actor", back_populates="movie_rows")
