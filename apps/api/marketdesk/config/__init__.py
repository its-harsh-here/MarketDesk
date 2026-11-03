"""Application configuration loaded from environment variables.

All operational secrets come from the environment; nothing here is exposed to the
frontend. ``validate_settings`` enforces production safety rules at startup.
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class ConfigError(RuntimeError):
    """Raised when the configuration is unsafe or incomplete."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=None, extra="ignore", case_sensitive=False)

    # Runtime mode
    marketdesk_env: Literal["development", "test", "production"] = "development"
    # yahoo = real market data. fixture = deterministic synthetic test harness (development/test only).
    data_provider: Literal["fixture", "yahoo"] = "yahoo"

    # Storage
    data_dir: Path = Field(default=REPO_ROOT / "data")
    database_url: str | None = None
    fixtures_dir: Path = Field(default=REPO_ROOT / "fixtures")
    starter_config_dir: Path = Field(default=REPO_ROOT / "config")
    static_dir: Path | None = None  # built SPA (apps/web/dist) served in production

    # Authentication
    owner_username: str | None = None
    owner_password_hash: str | None = None  # argon2 hash; generate with `marketdesk hash-password`
    session_secret: str | None = None
    session_ttl_hours: int = 24 * 90  # sliding: renewed daily while you use the app
    cookie_secure: bool | None = None  # defaults to True in production
    dev_auth_bypass: bool = False
    allowed_origins: str = ""  # comma-separated extra origins allowed for CSRF Origin checks / CORS
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Provider tuning (product defaults, not claims about Yahoo quotas)
    quote_ttl_seconds: int = 300
    history_ttl_seconds: int = 3600
    fundamentals_ttl_seconds: int = 86400
    search_ttl_seconds: int = 86400
    provider_timeout_seconds: float = 15.0
    provider_max_concurrency: int = 4
    provider_max_retries: int = 2
    circuit_failure_threshold: int = 5
    circuit_open_seconds: int = 60
    memory_cache_entries: int = 1024
    persisted_cache_rows: int = 4000

    # Worker
    alert_poll_seconds: int = 300
    # SEC EDGAR (US filings). No key exists; SEC requires an application name and a contact email in the User-Agent.
    sec_user_agent: str | None = None
    sec_max_requests_per_second: float = 5.0  # SEC fair-access limit is 10/s
    research_refresh_hours: int = 24  # how often tracked companies are re-checked for new filings
    worker_heartbeat_stale_seconds: int = 900

    # Limits
    max_watchlists: int = 20
    max_watchlist_items: int = 50
    max_symbols_per_request: int = 60
    max_upload_bytes: int = 1_000_000
    max_import_rows: int = 2000

    display_timezone_default: str = "Asia/Kolkata"

    @property
    def is_production(self) -> bool:
        return self.marketdesk_env == "production"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return normalize_database_url(self.database_url)
        return f"sqlite:///{(self.data_dir / 'marketdesk.db').as_posix()}"

    @property
    def uses_sqlite(self) -> bool:
        return self.effective_database_url.startswith("sqlite")

    @property
    def effective_cookie_secure(self) -> bool:
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @field_validator("owner_username", "owner_password_hash", mode="before")
    @classmethod
    def _strip_pasted_whitespace(cls, value):
        # Hosting dashboards make it easy to paste a trailing newline or space. A username or argon2 hash never
        # legitimately contains surrounding whitespace, and keeping it would reject the correct password.
        return value.strip() if isinstance(value, str) else value

    @property
    def extra_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def auth_mode(self) -> Literal["dev_bypass", "owner"]:
        if self.dev_auth_bypass:
            return "dev_bypass"
        return "owner"


def normalize_database_url(url: str) -> str:
    """Accept the plain URLs hosts hand out (postgres://, postgresql://) and use the bundled psycopg 3 driver."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


MAX_HASH_MEMORY_KIB = 256 * 1024  # an argon2 hash needing more memory than this cannot be verified on small hosts


def password_hash_problem(value: str | None) -> str | None:
    """Explain what is wrong with OWNER_PASSWORD_HASH, or None if it is a usable argon2 hash."""
    if not value:
        return "OWNER_PASSWORD_HASH is empty."
    if value[0] in "'\"" or value[-1] in "'\"":
        return (
            "OWNER_PASSWORD_HASH is wrapped in quotes. Remove them: quotes are only needed inside a .env file for "
            "Docker Compose, not in a hosting dashboard."
        )
    if "$$" in value:
        return "OWNER_PASSWORD_HASH contains '$$'; paste the hash exactly as `marketdesk hash-password` prints it."
    if not value.startswith("$argon2"):
        return "OWNER_PASSWORD_HASH must be an argon2 hash (it starts with $argon2id$); generate it with hash-password."
    from argon2 import extract_parameters
    from argon2.exceptions import InvalidHashError

    parts = value.split("$")  # ["", "argon2id", "v=19", "m=..,t=..,p=..", salt, digest]
    try:
        params = extract_parameters(value)
        complete = len(parts) == 6 and len(parts[4]) >= 11 and len(parts[5]) >= 22
        for chunk in parts[4:6] if complete else ():
            # Unpadded base64; a length that leaves one dangling character means the text was cut off.
            base64.b64decode(chunk + "=" * (-len(chunk) % 4), validate=True)
    except (InvalidHashError, ValueError, binascii.Error):
        complete = False
    if not complete:
        return "OWNER_PASSWORD_HASH is not a complete argon2 hash (it may have been cut off when pasting)."
    if params.memory_cost > MAX_HASH_MEMORY_KIB:
        return (
            f"OWNER_PASSWORD_HASH uses {params.memory_cost // 1024} MiB of memory per check, more than this server "
            "can reliably spare; generate a new hash with `marketdesk hash-password`."
        )
    return None


def validate_settings(settings: Settings, role: Literal["web", "worker"] = "web") -> None:
    """Fail fast on unsafe combinations. Called on API (role "web") and worker (role "worker") startup.

    The worker never authenticates browser requests, so it does not need the owner credentials or SESSION_SECRET.
    """
    problems: list[str] = []
    if settings.dev_auth_bypass and settings.marketdesk_env != "development":
        problems.append("DEV_AUTH_BYPASS is only allowed when MARKETDESK_ENV=development.")
    if settings.data_provider == "fixture" and settings.marketdesk_env == "production":
        problems.append(
            "DATA_PROVIDER=fixture is a synthetic test harness and is refused in production; use DATA_PROVIDER=yahoo."
        )
    if role == "worker":
        pass
    elif settings.is_production:
        if not settings.session_secret or len(settings.session_secret) < 32:
            problems.append("SESSION_SECRET (at least 32 characters) is required in production.")
        if not settings.owner_username:
            problems.append("OWNER_USERNAME is required in production.")
        hash_problem = password_hash_problem(settings.owner_password_hash)
        if hash_problem:
            problems.append(hash_problem)
    elif settings.auth_mode == "owner":
        if not (settings.owner_username and settings.owner_password_hash):
            problems.append(
                "Owner login is not configured. Set OWNER_USERNAME and OWNER_PASSWORD_HASH, "
                "or set DEV_AUTH_BYPASS=true for local development only."
            )
        elif password_hash_problem(settings.owner_password_hash):
            problems.append(password_hash_problem(settings.owner_password_hash) or "")
    if problems:
        raise ConfigError(" ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def session_secret_bytes(settings: Settings) -> bytes:
    """Secret used to HMAC session tokens. Development falls back to a per-data-dir random key."""
    if settings.session_secret:
        return settings.session_secret.encode()
    key_file = settings.data_dir / ".dev_session_secret"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_bytes(os.urandom(32).hex().encode())
        key_file.chmod(0o600)
    return key_file.read_bytes()
