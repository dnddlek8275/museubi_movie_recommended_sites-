"""add character preference type

Revision ID: 20260630_0002
Revises: 25d8a2a18004
Create Date: 2026-06-30
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260630_0002"
down_revision: str | None = "25d8a2a18004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 캐릭터 기반 취향 학습을 기존 취향 점수 테이블에 함께 저장할 수 있게 허용한다.
    op.drop_constraint(
        "ck_user_preference_scores_preference_type",
        "user_preference_scores",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_preference_scores_preference_type",
        "user_preference_scores",
        "preference_type IN ('genre', 'actor', 'director', 'keyword', 'language', 'character')",
    )


def downgrade() -> None:
    # character 취향 row가 남아 있으면 이전 제약으로 되돌릴 수 없어 먼저 제거한다.
    op.execute("DELETE FROM user_preference_scores WHERE preference_type = 'character'")
    op.drop_constraint(
        "ck_user_preference_scores_preference_type",
        "user_preference_scores",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_preference_scores_preference_type",
        "user_preference_scores",
        "preference_type IN ('genre', 'actor', 'director', 'keyword', 'language')",
    )
