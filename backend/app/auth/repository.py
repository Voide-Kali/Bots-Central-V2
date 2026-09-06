import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.db.models import AccessToken, RefreshToken, Session, User, UserEmail


class AuthRepository:
    """Minimal persistence lookups for future authentication services."""

    def __init__(self, session: DatabaseSession) -> None:
        self._session = session

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_user_email_by_canonical_email(self, email_canonical: str) -> UserEmail | None:
        statement = select(UserEmail).where(UserEmail.email_canonical == email_canonical)
        return self._session.scalar(statement)

    def get_session_by_id(self, session_id: uuid.UUID) -> Session | None:
        return self._session.get(Session, session_id)

    def get_access_token_by_digest(self, token_digest: bytes) -> AccessToken | None:
        statement = select(AccessToken).where(AccessToken.token_digest == token_digest)
        return self._session.scalar(statement)

    def get_refresh_token_by_digest(self, token_digest: bytes) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.token_digest == token_digest)
        return self._session.scalar(statement)
