"""Single-owner authentication: argon2 password hash from the environment, server-side
sessions (only an HMAC of the token is stored), CSRF tokens and login rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from marketdesk.config import Settings, session_secret_bytes
from marketdesk.models import AuthSession, LoginAttempt

COOKIE_NAME = "md_session"
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-the-password")


@dataclass(frozen=True)
class Principal:
    mode: str  # owner | dev_bypass | public_demo
    username: str
    csrf_token: str | None
    read_only: bool
    session_id: int | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _hmac(settings: Settings, value: str) -> str:
    return hmac.new(session_secret_bytes(settings), value.encode(), hashlib.sha256).hexdigest()


def client_key(settings: Settings, address: str | None) -> str:
    return _hmac(settings, f"client:{address or 'unknown'}")[:32]


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    expected_user = settings.owner_username or ""
    stored = settings.owner_password_hash or _DUMMY_HASH
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode()) and bool(expected_user)
    try:
        pw_ok = _hasher.verify(stored if user_ok else _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pw_ok = False
    return bool(user_ok and pw_ok and settings.owner_password_hash)


def login_blocked(db: Session, settings: Settings, key: str) -> int | None:
    """Return seconds until retry if too many recent failures from this client (or globally)."""
    since = datetime.now(UTC) - timedelta(minutes=settings.login_window_minutes)
    per_client = db.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.client_key == key, LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at >= since
        )
    ) or 0
    overall = db.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at >= since
        )
    ) or 0
    if per_client >= settings.login_max_failures or overall >= settings.login_max_failures * 4:
        return settings.login_window_minutes * 60
    return None


def record_attempt(db: Session, key: str, succeeded: bool) -> None:
    db.add(LoginAttempt(client_key=key, succeeded=succeeded))
    db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < datetime.now(UTC) - timedelta(days=2)))
    db.commit()


def create_session(db: Session, settings: Settings, username: str) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = AuthSession(
        token_hash=_hmac(settings, token),
        csrf_token=secrets.token_urlsafe(24),
        username=username,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(row)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    db.commit()
    return token, row


def lookup_session(db: Session, settings: Settings, token: str | None) -> AuthSession | None:
    if not token or len(token) > 200:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hmac(settings, token)))
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    if settings.owner_username and row.username != settings.owner_username:
        return None  # owner username was rotated
    if (now - row.last_seen_at) > timedelta(minutes=5):
        row.last_seen_at = now
        db.commit()
    return row


def revoke_session(db: Session, session_id: int) -> None:
    db.execute(update(AuthSession).where(AuthSession.id == session_id).values(revoked_at=datetime.now(UTC)))
    db.commit()


def revoke_all_sessions(db: Session) -> int:
    result = db.execute(
        update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
    )
    db.commit()
    return result.rowcount or 0


def dev_bypass_principal(settings: Settings) -> Principal:
    return Principal("dev_bypass", settings.owner_username or "owner", _hmac(settings, "dev-bypass-csrf")[:32], False)


def public_demo_principal() -> Principal:
    return Principal("public_demo", "demo", None, True)
