"""add recommended movies to chat messages

Revision ID: 20260701_0003
Revises: 20260630_0002
Create Date: 2026-07-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260701_0003"
down_revision: str | None = "20260630_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 챗봇 답변에 포함된 추천 영화 카드를 대화 당시 상태로 복원하기 위해 JSONB snapshot을 저장한다.
    op.add_column(
        "chat_messages",
        sa.Column("recommended_movies", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # 추천 영화 snapshot 컬럼을 제거한다.
    op.drop_column("chat_messages", "recommended_movies")
