from pydantic import BaseModel

from app.schemas.movie import ReadMovie


class RecommendedMovieRead(BaseModel):
    movie: ReadMovie
    recommendation_score: float
    matched_preferences: list[str]

