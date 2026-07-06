from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceError
from app.models.user import User
from app.schemas.user import CreateUser, UpdateUser


def create_user(db: Session, payload: CreateUser) -> User:
    # 회원가입 로직에서 검증이 끝난 사용자 정보를 DB에 저장한다.
    if get_user_by_email(db, payload.email) is not None:
        raise ServiceError("이미 가입된 이메일입니다.", status_code=409)

    user = User(
        email=payload.email,
        password_hash=payload.password_hash,
        nickname=payload.nickname,
        profile_image=payload.profile_image,
        preferred_genres=payload.preferred_genres,
        preferred_actors=payload.preferred_actors,
        preferred_keywords=payload.preferred_keywords,
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, payload: UpdateUser) -> User:
    # 마이페이지나 관리자 흐름에서 변경된 사용자 필드만 반영한다.
    user = get_user_or_404(db, user_id)
    update_data = payload.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


def get_user_or_404(db: Session, user_id: int) -> User:
    # 내부 로직에서 user_id 기준 사용자 존재 여부를 공통으로 확인한다.
    user = db.get(User, user_id)
    if user is None:
        raise ServiceError("사용자를 찾을 수 없습니다.", status_code=404)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    # 회원가입/로그인 로직에서 이메일 중복과 계정 존재 여부를 확인한다.
    return db.scalar(select(User).where(User.email == email))


def get_user_by_email_or_404(db: Session, email: str) -> User:
    # 로그인 로직에서 이메일로 사용자를 찾고 없으면 업무 실패로 처리한다.
    user = get_user_by_email(db, email)
    if user is None:
        raise ServiceError("존재하지 않는 이메일입니다.", status_code=404)
    return user


def get_password_hash_by_email(db: Session, email: str) -> str:
    # 비밀번호 검증은 auth 로직이 담당하므로 DB에서는 저장된 hash만 반환한다.
    return get_user_by_email_or_404(db, email).password_hash


def get_user_id_by_email(db: Session, email: str) -> int:
    # 토큰 발급 payload에 넣을 user_id를 이메일 기준으로 조회한다.
    return get_user_by_email_or_404(db, email).id


def get_nickname_by_email(db: Session, email: str) -> str:
    # 로그인 성공 응답에 포함할 nickname을 이메일 기준으로 조회한다.
    return get_user_by_email_or_404(db, email).nickname
