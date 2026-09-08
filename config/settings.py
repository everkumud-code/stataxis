from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    youtube_api_key: str
    database_url: str
    stx_log_level: str = "INFO"
    stx_user_agent: str = "STAXIS/0.1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
