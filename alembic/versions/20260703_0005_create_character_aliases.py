"""create character aliases

Revision ID: 20260703_0005
Revises: 20260701_0004
Create Date: 2026-07-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_0005"
down_revision: str | None = "20260701_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # /chat/auto에서 별칭을 정식 캐릭터명으로 매핑하기 위한 별도 테이블을 만든다.
    op.create_table(
        "character_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("character_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_character_aliases_character_id", "character_aliases", ["character_id"])
    op.create_index("ix_character_aliases_alias", "character_aliases", ["alias"], unique=True)


def downgrade() -> None:
    # 캐릭터 별칭 테이블과 인덱스를 제거한다.
    op.drop_index("ix_character_aliases_alias", table_name="character_aliases")
    op.drop_index("ix_character_aliases_character_id", table_name="character_aliases")
    op.drop_table("character_aliases")
