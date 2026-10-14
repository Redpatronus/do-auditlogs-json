from datetime import timedelta
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration from env vars (prefix DOAL_) or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="DOAL_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    base_url: str = "https://cloud.digitalocean.com"
    # DigitalOcean has no audit-log API; the data lives on this UI page (Security > History).
    audit_path: str = "/security/history"

    # Playwright storage_state JSON (cookies) created by `do-audit login`. Treat as a secret.
    storage_state_path: Path = Path("data/storage_state.json")
    output_path: Path = Path("data/audit_logs.ndjson")
    state_path: Path = Path("data/state.json")
    lock_path: Path = Path("data/scrape.lock")

    # Headless Chromium is challenged by Cloudflare; default is a normal window (on a Linux
    # server without a display a virtual Xvfb display is started automatically).
    headless: bool = False
    max_pages: int = Field(default=100, ge=1)
    nav_timeout_ms: int = 45_000
    page_delay_s: float = 1.5  # politeness delay between pages
    seen_cache_size: int = Field(default=20_000, ge=100)

    # UI selectors, kept configurable because DO can change its DOM.
    # Security History is a div-based list; this row selector confirms the page rendered.
    table_selector: str = "[data-testid='team-audit-action-row']"
    next_button_selector: str = "[data-testid='paginator/increment']"

    # Optional server-side auto-login (no laptop needed). Keep these in a 0600 .env or
    # systemd credentials, never in git. Requires a local DO account with TOTP 2FA (not SSO).
    email: str | None = None
    password: SecretStr | None = None
    totp_secret: SecretStr | None = None  # base32 secret shown when enabling the authenticator app
    login_path: str = "/login"
    email_selector: str = "input[name='email'], input[type='email']"
    password_selector: str = "input[type='password']"  # noqa: S105
    totp_selector: str = "input[name='code'], input[autocomplete='one-time-code']"
    submit_selector: str = "button[type='submit']"

    # How long the cached session is reused before a fresh login is forced. Set ONE of the two
    # (both empty = 7 days). Keep it at or below the session lifetime configured in DigitalOcean.
    session_max_age_days: int | None = Field(default=None, ge=1)
    session_max_age_hours: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_session_age(self) -> "Settings":
        if self.session_max_age_days is not None and self.session_max_age_hours is not None:
            raise ValueError(
                "set only one of DOAL_SESSION_MAX_AGE_DAYS / DOAL_SESSION_MAX_AGE_HOURS"
            )
        return self

    @property
    def session_max_age(self) -> timedelta:
        if self.session_max_age_hours is not None:
            return timedelta(hours=self.session_max_age_hours)
        return timedelta(days=self.session_max_age_days or 7)

    log_level: str = "INFO"
    log_json: bool = True

    @property
    def session_meta_path(self) -> Path:
        return self.storage_state_path.with_suffix(".meta")

    @property
    def can_auto_login(self) -> bool:
        return bool(self.email and self.password and self.totp_secret)

    @property
    def audit_url(self) -> str:
        return self.base_url.rstrip("/") + self.audit_path
