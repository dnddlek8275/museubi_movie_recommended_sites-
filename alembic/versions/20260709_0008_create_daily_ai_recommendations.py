"""create daily ai recommendations

Revision ID: 20260709_0008
Revises: 20260706_0007
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_0008"
down_revision: str | None = "20260706_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AI가 하루 단위로 생성한 추천 한 문장과 추천 영화 묶음을 저장한다.
    op.create_table(
        "daily_ai_recommendations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("recommend_date", sa.Date(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_daily_ai_recommendations_recommend_date", "daily_ai_recommendations", ["recommend_date"], unique=True)

    op.create_table(
        "daily_ai_recommendation_movies",
        sa.Column("daily_recommendation_id", sa.BigInteger(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["daily_recommendation_id"], ["daily_ai_recommendations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("daily_recommendation_id", "movie_id"),
        sa.UniqueConstraint("daily_recommendation_id", "display_order", name="uq_daily_ai_recommendation_movies_order"),
        sa.CheckConstraint("display_order BETWEEN 1 AND 3", name="ck_daily_ai_recommendation_movies_display_order"),
    )


def downgrade() -> None:
    # 추천 영화 연결 테이블을 먼저 제거한 뒤 추천 묶음 테이블을 제거한다.
    op.drop_table("daily_ai_recommendation_movies")
    op.drop_index("ix_daily_ai_recommendations_recommend_date", table_name="daily_ai_recommendations")
    op.drop_table("daily_ai_recommendations")
