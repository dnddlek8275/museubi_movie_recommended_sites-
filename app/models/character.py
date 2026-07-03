from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 영화가 삭제되어도 캐릭터 대화 설정은 남길 수 있게 연결만 해제한다.
    movie_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("movies.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    movie_title: Mapped[str] = mapped_column(String(200), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lang: Mapped[str] = mapped_column(String(10), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    profile_image: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    movie = relationship("Movie")
    alias_rows = relationship(
        "CharacterAlias",
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def aliases(self) -> list[str]:
        # Pydantic 응답에서는 별칭 row 객체 대신 문자열 목록으로 보여준다.
        return [alias.alias for alias in self.alias_rows]


class CharacterAlias(Base):
    __tablename__ = "character_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("characters.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)

    # /chat/auto에서 별칭을 정식 캐릭터명으로 되돌릴 수 있도록 원본 캐릭터와 연결한다.
    character = relationship("Character", back_populates="alias_rows")
