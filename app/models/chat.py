from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class ChatRoom(TimestampMixin, Base):
    __tablename__ = "chat_rooms"
    # 채팅 구현이 별도 모듈에 있어도 기록 저장을 위해 DB 제약은 모델에서 보장한다.
    __table_args__ = (
        CheckConstraint("room_type IN ('general', 'character', 'group')", name="ck_chat_rooms_room_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    room_type: Mapped[str] = mapped_column(String(20), nullable=False)
    characters: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    messages = relationship("ChatMessage", back_populates="room", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    character_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 추천 영화는 대화 히스토리 화면 복원용 snapshot으로 저장한다.
    recommended_movies: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    room = relationship("ChatRoom", back_populates="messages")
