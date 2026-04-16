from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Data Quality Control Center"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60 * 24
    database_url: str = "postgresql+psycopg://app:app@127.0.0.1:5432/data_quality"
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    sendgrid_api_key: str | None = None
    email_from: str = "no-reply@datacontrol.local"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    frontend_url: str = "http://127.0.0.1:3000"
    google_redirect_uri: str | None = None


settings = Settings()
