"""Application configuration loaded from environment variables.

All operational secrets come from the environment; nothing here is exposed to the
frontend. ``validate_settings`` enforces production safety rules at startup.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    session_ttl_hours: int = 24 * 14
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
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'marketdesk.db').as_posix()}"

    @property
    def effective_cookie_secure(self) -> bool:
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @property
    def extra_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def auth_mode(self) -> Literal["dev_bypass", "owner"]:
        if self.dev_auth_bypass:
            return "dev_bypass"
        return "owner"


def validate_settings(settings: Settings) -> None:
    """Fail fast on unsafe combinations. Called on API and worker startup."""
    problems: list[str] = []
    if settings.dev_auth_bypass and settings.marketdesk_env != "development":
        problems.append("DEV_AUTH_BYPASS is only allowed when MARKETDESK_ENV=development.")
    if settings.data_provider == "fixture" and settings.marketdesk_env == "production":
        problems.append(
            "DATA_PROVIDER=fixture is a synthetic test harness and is refused in production; use DATA_PROVIDER=yahoo."
        )
    if settings.is_production:
        if not settings.session_secret or len(settings.session_secret) < 32:
            problems.append("SESSION_SECRET (at least 32 characters) is required in production.")
        if not settings.owner_username:
            problems.append("OWNER_USERNAME is required in production.")
        if not settings.owner_password_hash or not settings.owner_password_hash.startswith("$argon2"):
            problems.append("OWNER_PASSWORD_HASH (argon2 hash) is required in production.")
    elif settings.auth_mode == "owner":
        if not (settings.owner_username and settings.owner_password_hash):
            problems.append(
                "Owner login is not configured. Set OWNER_USERNAME and OWNER_PASSWORD_HASH, "
                "or set DEV_AUTH_BYPASS=true for local development only."
            )
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
