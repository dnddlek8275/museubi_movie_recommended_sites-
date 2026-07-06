from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.exceptions import ServiceError
from app.models.actor import Actor
from app.models.character import Character
from app.models.chat import ChatMessage
from app.models.movie import Movie
from app.schemas.actor import CreateActor, CreateMovieActor
from app.schemas.auth import CreateRefreshToken
from app.schemas.chat import CreateChatMessage, CreateChatRoom
from app.schemas.character import CreateCharacter, UpdateCharacter
from app.schemas.movie import CreateMovie
from app.schemas.user import CreateUser
from app.services.actor_service import link_movie_actor, list_movies_by_actor, upsert_actor_from_tmdb
from app.services.admin_service import create_character, create_movie, get_admin_stats, update_character
from app.services.auth_service import create_refresh_token, revoke_refresh_token, verify_refresh_token
from app.services.chat_service import create_chat_message, create_chat_room, get_character_by_name_or_alias
from app.services.interaction_service import record_movie_interaction, resolve_action_type
from app.services.movie_search_service import search_movies
from app.services.preference_service import list_user_preference_scores, update_user_character_preference_score
from app.services.recommendation_service import recommend_movies_for_user
from app.services.ranking_service import list_top_movies
from app.services.user_activity_service import list_user_liked_movies, list_user_view_history
from app.services.user_service import create_user, get_user_by_email

DEMO_EMAIL = "demo-user@cineverse.testmail.com"
DEMO_TMDB_ID = 990001
DEMO_TOKEN_PREFIX = "demo-refresh-token-hash"


def main() -> None:
    # B1 연결 없이 DB/service 모듈의 주요 흐름을 한 번에 검증한다.
    with SessionLocal() as db:
        user = get_or_create_demo_user(db)
        movie = get_or_create_demo_movie(db)
        character = get_or_create_demo_character(db, movie)
        actor = get_or_create_demo_actor(db, movie)

        record_demo_interactions(db, user_id=user.id, movie_id=movie.id)
        record_demo_character_preferences(db, user_id=user.id, character_id=character.id)
        verify_demo_character_alias(db, character_name=character.name)
        verify_demo_refresh_token(db, user_id=user.id)
        recommendations = recommend_movies_for_user(
            db,
            user.id,
            limit=5,
            exclude_interacted=False,
        )
        chat_message = save_demo_recommended_movies_message(
            db,
            user_id=user.id,
            character_name=character.name,
            recommendations=recommendations,
        )

        print_result(
            user_id=user.id,
            movie_id=movie.id,
            character_id=character.id,
            actor_id=actor.id,
            chat_message_id=chat_message.id,
            ranking=list_top_movies(db, limit=5),
            preferences=list_user_preference_scores(db, user.id, limit=10),
            character_preferences=list_user_preference_scores(
                db,
                user.id,
                preference_type="character",
                limit=10,
            ),
            recommendations=recommendations,
            actor_movies=list_movies_by_actor(db, actor.id, limit=5),
            recommended_movies_snapshot=chat_message.recommended_movies or [],
            search_results=search_movies(db, "드라마", limit=5),
            liked_movies=list_user_liked_movies(db, user.id, limit=5),
            view_history=list_user_view_history(db, user.id, limit=5),
            stats=get_admin_stats(db),
        )


def get_or_create_demo_user(db):
    # 같은 이메일의 데모 사용자가 있으면 재사용하고, 없으면 새로 만든다.
    user = get_user_by_email(db, DEMO_EMAIL)
    if user is not None:
        return user

    return create_user(
        db,
        CreateUser(
            email=DEMO_EMAIL,
            password_hash="demo-password-hash",
            nickname="데모유저",
            preferred_genres=["드라마"],
            preferred_actors=["테스트 배우1"],
            preferred_keywords=["성장"],
        ),
    )


def get_or_create_demo_movie(db):
    # 같은 TMDB ID의 데모 영화가 있으면 재사용하고, 없으면 새로 만든다.
    movie = db.scalar(select(Movie).where(Movie.tmdb_id == DEMO_TMDB_ID))
    if movie is not None:
        return movie

    return create_movie(
        db,
        CreateMovie(
            tmdb_id=DEMO_TMDB_ID,
            title="서비스 검증용 영화",
            overview="DB/service 모듈 검증을 위한 데모 영화입니다.",
            genres=["드라마", "가족"],
            director="테스트 감독",
            cast=["테스트 배우1", "테스트 배우2"],
            keywords=["성장", "우정"],
            year=2026,
            language="ko",
            vote_average=8.5,
            vote_count=120,
            audience_count=15000,
            poster_path="/demo-service-movie.jpg",
            last_synced_at=datetime.now(timezone.utc),
        ),
    )


def get_or_create_demo_character(db, movie: Movie):
    # 같은 영화에 연결된 데모 캐릭터가 있으면 재사용하고, 없으면 새로 만든다.
    character = db.scalar(
        select(Character).where(
            Character.movie_id == movie.id,
            Character.name == "데모 캐릭터",
        )
    )
    if character is not None:
        ensure_demo_character_aliases(db, character.id)
        return character

    return create_character(
        db,
        CreateCharacter(
            movie_id=movie.id,
            name="데모 캐릭터",
            movie_title=movie.title,
            actor="테스트 배우1",
            aliases=["검증 캐릭터", "테스트 캐릭터"],
            lang="ko",
            system_prompt="너는 서비스 검증을 위한 데모 캐릭터다.",
            profile_image="/demo-character.jpg",
            is_active=True,
        ),
    )


def ensure_demo_character_aliases(db, character_id: int) -> None:
    # 기존 데모 캐릭터를 재사용하는 경우에도 별칭 검증 데이터가 존재하도록 보정한다.
    update_character(
        db,
        character_id,
        UpdateCharacter(aliases=["검증 캐릭터", "테스트 캐릭터"]),
    )


def get_or_create_demo_actor(db, movie: Movie) -> Actor:
    # TMDB credits 동기화 결과처럼 데모 배우를 만들고 데모 영화와 연결한다.
    actor = upsert_actor_from_tmdb(
        db,
        CreateActor(
            tmdb_actor_id=990101,
            name="테스트 배우1",
            profile_path="/demo-actor-profile.jpg",
        ),
    )
    link_movie_actor(
        db,
        CreateMovieActor(
            movie_id=movie.id,
            actor_id=actor.id,
            character_name="검증 배역",
            cast_order=0,
        ),
    )
    return actor


def record_demo_interactions(db, *, user_id: int, movie_id: int) -> None:
    # 조회, 검색 후 조회, 좋아요를 모두 기록해 랭킹과 취향 점수 갱신을 확인한다.
    record_movie_interaction(
        db,
        user_id=user_id,
        movie_id=movie_id,
        action_type=resolve_action_type("direct"),
        source="direct",
    )
    record_movie_interaction(
        db,
        user_id=user_id,
        movie_id=movie_id,
        action_type=resolve_action_type("search"),
        source="search",
    )
    record_movie_interaction(
        db,
        user_id=user_id,
        movie_id=movie_id,
        action_type="like",
        source="direct",
    )


def record_demo_character_preferences(db, *, user_id: int, character_id: int) -> None:
    # 캐릭터 선택과 대화를 각각 취향 점수로 반영한다.
    update_user_character_preference_score(
        db,
        user_id=user_id,
        character_id=character_id,
        action_type="select",
    )
    update_user_character_preference_score(
        db,
        user_id=user_id,
        character_id=character_id,
        action_type="chat",
    )


def verify_demo_character_alias(db, *, character_name: str) -> None:
    # /chat/auto에서 정식 이름과 별칭이 같은 캐릭터로 매핑되는지 확인한다.
    by_name = get_character_by_name_or_alias(db, character_name)
    by_alias = get_character_by_name_or_alias(db, "검증 캐릭터")
    if by_name is None or by_alias is None or by_name.id != by_alias.id:
        raise ServiceError("캐릭터 별칭 매핑 검증에 실패했습니다.", status_code=500)


def verify_demo_refresh_token(db, *, user_id: int) -> None:
    # Refresh Token 저장/검증/폐기 흐름이 service 함수만으로 동작하는지 확인한다.
    token_hash = f"{DEMO_TOKEN_PREFIX}-{datetime.now(timezone.utc).timestamp()}"
    try:
        create_refresh_token(
            db,
            CreateRefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                user_agent="service-verify-script",
            ),
        )
    except ServiceError as exc:
        if exc.status_code != 409:
            raise

    token = verify_refresh_token(db, token_hash)
    revoked_token = revoke_refresh_token(db, token_hash)

    print(f"refresh token verified: token_id={token.id}, revoked_at={revoked_token.revoked_at}")


def save_demo_recommended_movies_message(
    db,
    *,
    user_id: int,
    character_name: str,
    recommendations: list[dict],
) -> ChatMessage:
    # 추천 영화 JSONB snapshot이 chat_messages에 저장되는지 검증한다.
    room = create_chat_room(
        db,
        CreateChatRoom(
            user_id=user_id,
            room_type="character",
            characters=[character_name],
        ),
    )
    return create_chat_message(
        db,
        CreateChatMessage(
            room_id=room.id,
            role="assistant",
            character_name=character_name,
            content="취향을 바탕으로 이런 영화를 추천해요.",
            recommended_movies=build_llm_recommended_movies_payload(recommendations),
        ),
    )


def build_llm_recommended_movies_payload(recommendations: list[dict]) -> list[dict]:
    # LLM 응답 예시처럼 tmdb_id 중심의 추천 영화 JSON을 만든다.
    payload = []
    for rank, recommendation in enumerate(recommendations, start=1):
        movie = recommendation["movie"]
        payload.append(
            {
                "tmdb_id": str(movie["tmdb_id"]),
                "title": movie["title"],
                "year": movie["year"],
                "genres": movie["genres"],
                "director": movie["director"],
                "cast": movie["cast"],
                "vote_average": movie["vote_average"],
                "overview": movie["overview"],
                "poster_path": movie["poster_path"],
                "rank": rank,
                "recommendation_score": recommendation["recommendation_score"],
                "matched_preferences": recommendation["matched_preferences"],
            }
        )
    return payload


def print_result(
    *,
    user_id: int,
    movie_id: int,
    character_id: int,
    actor_id: int,
    chat_message_id: int,
    ranking: list[dict],
    preferences: list,
    character_preferences: list,
    recommendations: list[dict],
    actor_movies: list[dict],
    recommended_movies_snapshot: list[dict],
    search_results: list[dict],
    liked_movies: list[dict],
    view_history: list[dict],
    stats: dict,
) -> None:
    # 검증 결과를 터미널에서 빠르게 확인할 수 있게 핵심 값만 출력한다.
    print("service verification complete")
    print(f"user_id={user_id}, movie_id={movie_id}, character_id={character_id}, actor_id={actor_id}, chat_message_id={chat_message_id}")
    print(f"ranking_top={ranking[:3]}")
    print(
        "preferences_top="
        + str(
            [
                {
                    "type": item.preference_type,
                    "value": item.preference_value,
                    "score": item.score,
                }
                for item in preferences[:5]
            ]
        )
    )
    print(
        "character_preferences="
        + str(
            [
                {
                    "value": item.preference_value,
                    "score": item.score,
                }
                for item in character_preferences
            ]
        )
    )
    print(f"recommendations_top={recommendations[:3]}")
    print(f"actor_movies_top={actor_movies[:3]}")
    print(f"recommended_movies_snapshot={recommended_movies_snapshot[:3]}")
    print(f"search_results_top={search_results[:3]}")
    print(f"liked_movies_count={len(liked_movies)}")
    print(f"view_history_count={len(view_history)}")
    print(f"stats={stats}")


if __name__ == "__main__":
    main()
