from app.core.database import Base
from app.models.actor import Actor, MovieActor
from app.models.admin import AdminAuditLog
from app.models.character import Character, CharacterAlias
from app.models.chat import ChatMessage, ChatRoom
from app.models.daily_recommendation import DailyAiRecommendation, DailyAiRecommendationMovie
from app.models.interaction import MovieStats, UserMovieInteraction, UserPreferenceScore
from app.models.movie import Movie, MovieGenre
from app.models.user import User, RefreshToken


# Alembic autogenerate가 전체 모델 메타데이터를 볼 수 있도록 모델 import를 한곳에 모은다.
__all__ = [
    "AdminAuditLog",
    "Actor",
    "Base",
    "Character",
    "CharacterAlias",
    "ChatMessage",
    "ChatRoom",
    "DailyAiRecommendation",
    "DailyAiRecommendationMovie",
    "Movie",
    "MovieActor",
    "MovieGenre",
    "MovieStats",
    "User",
    "RefreshToken",
    "UserMovieInteraction",
    "UserPreferenceScore",
]
