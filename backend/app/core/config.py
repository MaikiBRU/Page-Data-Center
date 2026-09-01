from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that are obviously placeholders rather than secrets. The first was
# this project's own default until it was removed: an instance booted without
# SECRET_KEY signed its JWTs with a string published in the repository, so
# anyone could mint an administrator token.
_PLACEHOLDER_SECRETS = {
    "change-me",
    "changeme",
    "change_me",
    "changethis",
    "secret",
    "secret-key",
    "your-secret-key",
    "test",
    "todo",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Data Quality Control Center"

    # "development" or "production". Only used to decide what to expose; every
    # security control below is applied in both, so a misconfigured value
    # cannot switch protection off.
    environment: str = "development"

    # Required, with no default of any kind: the application must refuse to
    # start rather than sign tokens with a key somebody could guess.
    secret_key: str = Field(min_length=1)
    access_token_expire_minutes: int = 60 * 24

    # --- API documentation --------------------------------------------------
    # /docs, /redoc and /openapi.json enumerate every endpoint and its schema.
    # Useful while developing, an inventory for anyone else. Off in production
    # unless deliberately turned back on.
    expose_api_docs: bool | None = None

    # --- Brute force protection ---------------------------------------------
    # Two windows per endpoint: one keyed on the address, one on the address
    # plus the account being targeted. The per-account window is cleared on a
    # successful sign-in, so somebody typing their own password correctly is
    # never locked out by earlier mistakes.
    login_max_attempts_per_account: int = 10
    login_max_attempts_per_ip: int = 40
    login_rate_window_seconds: int = 900

    forgot_password_max_per_account: int = 3
    forgot_password_max_per_ip: int = 15
    forgot_password_rate_window_seconds: int = 3600

    # --- Password reset delivery --------------------------------------------
    # When true the reset link is printed and written to logs/password_reset.log
    # so a local developer can follow the flow without SendGrid. It puts a
    # working token in a file and on stdout, so it must never be on outside
    # development.
    reset_link_to_logs: bool = False
    database_url: str = "postgresql+psycopg://app:app@127.0.0.1:5432/data_quality"
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    sendgrid_api_key: str | None = None
    email_from: str = "no-reply@datacontrol.local"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    frontend_url: str = "http://127.0.0.1:3000"
    google_redirect_uri: str | None = None

    # --- account creation ---------------------------------------------------
    # There is no public sign-up. Visitors use the demo sandbox, which needs no
    # account at all, and real accounts are created by an administrator through
    # POST /users. Signing in with Google therefore authenticates an *existing*
    # user by default; it does not create one.
    #
    # Set this to true only if you deliberately want any Google account to be
    # able to provision itself, and prefer google_allowed_emails when you just
    # need to let a known person in.
    google_auto_provision: bool = False

    # Comma separated allowlist. Emails here may sign in with Google even if
    # they have no account yet, which is how the owner gets back in after the
    # database is rebuilt without opening the door to everyone.
    google_allowed_emails: str = ""

    # Email promoted to administrator at startup when the instance has no
    # administrator yet. Replaces the previous behaviour of promoting whichever
    # user happened to have the lowest id.
    bootstrap_admin_email: str | None = None

    @property
    def google_allowlist(self) -> set[str]:
        return {
            item.strip().lower()
            for item in (self.google_allowed_emails or "").split(",")
            if item.strip()
        }

    # --- Demo sandbox -------------------------------------------------------
    # Master switch. When false the /demo endpoints return 404 and no demo
    # token can be minted, leaving the authenticated app untouched.
    demo_enabled: bool = True

    # Per-session quotas. Defaults come from measured cost:
    #   parsing a CSV into records costs ~12x the file size in RAM
    #   the quality pipeline costs ~28 microseconds per row
    # 2 MB => ~11k rows => ~250 ms CPU => ~24 MB peak RAM per request.
    demo_max_datasets: int = 3
    demo_max_file_size_mb: float = 2.0
    demo_max_storage_mb: float = 6.0
    demo_max_runs: int = 20
    demo_max_exports: int = 30

    # Lifetime.
    demo_session_ttl_minutes: int = 45
    demo_idle_timeout_minutes: int = 20

    # Rows generated for the seeded sandbox datasets.
    demo_seed_rows: int = 400
    demo_seed_anomaly_rate: float = 0.12

    # Abuse control for session creation (in-process sliding window).
    demo_rate_limit_per_hour: int = 12
    demo_max_active_sessions: int = 200

    # Background cleanup loop interval. 0 disables the loop (the protected
    # maintenance endpoint still works).
    demo_cleanup_interval_seconds: int = 300

    # Shared secret for POST /demo/maintenance/cleanup. When unset the
    # endpoint is disabled rather than open.
    demo_maintenance_token: str | None = None

    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        """A blank or placeholder signing key is the same as having none."""
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError(
                "SECRET_KEY no puede estar vacia. Generá un valor aleatorio largo, "
                "por ejemplo con: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if cleaned.lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "SECRET_KEY tiene un valor de ejemplo. Generá uno real y aleatorio."
            )
        return cleaned

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def docs_enabled(self) -> bool:
        """Explicit setting wins; otherwise documentation is dev-only."""
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return not self.is_production

    @property
    def reset_link_logging_enabled(self) -> bool:
        """Never in production, whatever the flag says.

        A reset link is a working credential. The flag exists for local
        convenience and is not a decision production is allowed to make.
        """
        return self.reset_link_to_logs and not self.is_production

    @property
    def demo_max_file_size_bytes(self) -> int:
        return int(self.demo_max_file_size_mb * 1024 * 1024)

    @property
    def demo_max_storage_bytes(self) -> int:
        return int(self.demo_max_storage_mb * 1024 * 1024)


settings = Settings()
