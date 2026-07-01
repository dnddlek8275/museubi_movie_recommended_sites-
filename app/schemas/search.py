from app.schemas.movie import ReadMovie


class MovieSearchResultRead(ReadMovie):
    search_score: float
    matched_fields: list[str]
