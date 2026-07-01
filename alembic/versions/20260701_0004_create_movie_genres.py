"""create movie genres

Revision ID: 20260701_0004
Revises: 20260701_0003
Create Date: 2026-07-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0004"
down_revision: str | None = "20260701_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 장르별 검색/추천/집계를 위해 movies.genres 배열을 별도 row 테이블로 정규화한다.
    op.create_table(
        "movie_genres",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("genre", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("movie_id", "genre", name="uq_movie_genres_movie_genre"),
    )
    op.create_index("ix_movie_genres_movie_id", "movie_genres", ["movie_id"])
    op.create_index("ix_movie_genres_genre", "movie_genres", ["genre"])

    # 기존 movies.genres 배열에 들어 있던 값을 새 정규화 테이블로 옮긴다.
    op.execute(
        """
        INSERT INTO movie_genres (movie_id, genre)
        SELECT movies.id, trimmed.genre
        FROM movies
        CROSS JOIN LATERAL (
            SELECT DISTINCT btrim(genre_value) AS genre
            FROM unnest(movies.genres) AS genre_value
            WHERE btrim(genre_value) <> ''
        ) AS trimmed
        WHERE movies.genres IS NOT NULL
        """
    )


def downgrade() -> None:
    # 정규화 테이블만 제거한다. movies.genres 컬럼은 호환을 위해 유지되어 있으므로 복구 작업은 필요 없다.
    op.drop_index("ix_movie_genres_genre", table_name="movie_genres")
    op.drop_index("ix_movie_genres_movie_id", table_name="movie_genres")
    op.drop_table("movie_genres")
