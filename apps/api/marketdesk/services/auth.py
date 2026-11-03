"""Single-owner authentication: argon2 password hash from the environment, signed session
cookies (HMAC with SESSION_SECRET, server-side revocation), CSRF tokens and login rate limiting."""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import secrets
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from marketdesk.config import Settings, session_secret_bytes
from marketdesk.models import AppSetting, LoginAttempt

COOKIE_NAME = "md_session"
_hasher = PasswordHasher()


@functools.cache
def _dummy_hash() -> str:
    # Verified against when the username is wrong, so timing does not reveal valid usernames. Computed
    # on first use: an argon2 hash costs about a second of CPU time on a 0.1-CPU host at startup.
    return _hasher.hash("not-the-password")


@dataclass(frozen=True)
class Principal:
    mode: str  # owner | dev_bypass
    username: str
    csrf_token: str | None
    read_only: bool
    session_id: str | None = None
    claims: dict | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _hmac(settings: Settings, value: str) -> str:
    return hmac.new(session_secret_bytes(settings), value.encode(), hashlib.sha256).hexdigest()


def client_key(settings: Settings, address: str | None) -> str:
    return _hmac(settings, f"client:{address or 'unknown'}")[:32]


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    expected_user = settings.owner_username or ""
    stored = settings.owner_password_hash or _dummy_hash()
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode()) and bool(expected_user)
    try:
        pw_ok = _hasher.verify(stored if user_ok else _dummy_hash(), password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pw_ok = False
    return bool(user_ok and pw_ok and settings.owner_password_hash)


def login_blocked(db: Session, settings: Settings, key: str) -> int | None:
    """Return seconds until retry if too many recent failures from this client (or globally)."""
    since = datetime.now(UTC) - timedelta(minutes=settings.login_window_minutes)
    per_client = (
        db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.client_key == key, LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at >= since
            )
        )
        or 0
    )
    overall = (
        db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at >= since)
        )
        or 0
    )
    if per_client >= settings.login_max_failures or overall >= settings.login_max_failures * 4:
        return settings.login_window_minutes * 60
    return None


def record_attempt(db: Session, key: str, succeeded: bool) -> None:
    db.add(LoginAttempt(client_key=key, succeeded=succeeded))
    db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < datetime.now(UTC) - timedelta(days=2)))
    db.commit()


# --------------------------------------------------------------------------- sessions
# Signed session cookies: the cookie carries {user, issued-at, expiry, session id, csrf} plus an
# HMAC-SHA256 signature keyed by SESSION_SECRET. Sign-ins therefore survive restarts, redeploys and
# database resets. They end on expiry (sliding: renewed daily while used), explicit sign-out (the
# session id is revoked server-side), "sign out everywhere" (a revocation epoch), rotating
# SESSION_SECRET, or changing OWNER_USERNAME.
REFRESH_AFTER_SECONDS = 24 * 3600
_REVOKED_KEY = "revoked_sessions"
_EPOCH_KEY = "sessions_valid_after"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(settings: Settings, payload: str) -> str:
    return _b64(hmac.new(session_secret_bytes(settings), f"md1.{payload}".encode(), hashlib.sha256).digest())


def issue_session(settings: Settings, username: str, *, csrf: str | None = None, sid: str | None = None):
    now = int(time.time())
    claims = {
        "u": username,
        "iat": now,
        "exp": now + settings.session_ttl_hours * 3600,
        "sid": sid or secrets.token_urlsafe(12),
        "csrf": csrf or secrets.token_urlsafe(24),
    }
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{payload}.{_signature(settings, payload)}", claims


# The revocation state (sign-out list and "sign out everywhere" epoch) is read on every
# authenticated request, so it is cached per database for a few seconds. Sign-out in this process
# clears the cache at once; a `marketdesk revoke-sessions` run elsewhere applies within this window.
REVOCATION_CACHE_SECONDS = 15.0
_revocation_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_revocation_lock = threading.Lock()
_revocation_generation = 0  # bumped on every revocation so a read that raced it is not cached
_clock = time.monotonic


def clear_revocation_cache() -> None:
    global _revocation_generation
    with _revocation_lock:
        _revocation_generation += 1
        _revocation_cache.clear()


def _revocation_state(db: Session) -> tuple[object, object]:
    pool = db.get_bind().pool
    now = _clock()
    with _revocation_lock:
        generation = _revocation_generation
        hit = _revocation_cache.get(pool)
    if hit is not None and hit[0] > now:
        return hit[1], hit[2]
    rows = {
        key: value
        for key, value in db.execute(
            select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_([_EPOCH_KEY, _REVOKED_KEY]))
        )
    }
    epoch, revoked = rows.get(_EPOCH_KEY), rows.get(_REVOKED_KEY)
    with _revocation_lock:
        if generation == _revocation_generation:
            _revocation_cache[pool] = (now + REVOCATION_CACHE_SECONDS, epoch, revoked)
    return epoch, revoked


def read_session(db: Session, settings: Settings, token: str | None) -> dict | None:
    if not token or len(token) > 1024 or token.count(".") != 1:
        return None
    payload, sig = token.split(".")
    if not hmac.compare_digest(sig, _signature(settings, payload)):
        return None
    try:
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    now = time.time()
    if not isinstance(claims, dict) or claims.get("exp", 0) <= now:
        return None
    if not settings.owner_username or claims.get("u") != settings.owner_username:
        return None  # owner username was changed
    epoch, revoked = _revocation_state(db)
    if isinstance(epoch, (int, float)) and claims.get("iat", 0) < epoch:
        return None
    if isinstance(revoked, dict) and claims.get("sid") in revoked:
        return None
    return claims


def needs_refresh(claims: dict) -> bool:
    return time.time() - claims.get("iat", 0) > REFRESH_AFTER_SECONDS


def revoke_session(db: Session, claims: dict) -> None:
    row = db.get(AppSetting, _REVOKED_KEY)
    now = time.time()
    revoked = {k: v for k, v in (row.value or {}).items() if v > now} if row is not None else {}
    revoked[claims["sid"]] = claims["exp"]
    if row is None:
        db.add(AppSetting(key=_REVOKED_KEY, value=revoked))
    else:
        row.value = revoked
    db.commit()
    clear_revocation_cache()


def revoke_all_sessions(db: Session) -> None:
    """Sign out every browser: sessions issued before now stop working."""
    now = int(time.time()) + 1
    row = db.get(AppSetting, _EPOCH_KEY)
    if row is None:
        db.add(AppSetting(key=_EPOCH_KEY, value=now))
    else:
        row.value = now
    db.commit()
    clear_revocation_cache()


def dev_bypass_principal(settings: Settings) -> Principal:
    return Principal("dev_bypass", settings.owner_username or "owner", _hmac(settings, "dev-bypass-csrf")[:32], False)
