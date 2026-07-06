"""add user profile image

Revision ID: 20260706_0006
Revises: 20260703_0005
Create Date: 2026-07-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_0006"
down_revision: str | None = "20260703_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 실제 이미지 파일은 외부 저장소/서버 폴더에 두고 DB에는 접근 경로만 저장한다.
    op.add_column("users", sa.Column("profile_image", sa.String(length=300), nullable=True))


def downgrade() -> None:
    # 사용자 프로필 이미지 경로 컬럼을 제거한다.
    op.drop_column("users", "profile_image")
