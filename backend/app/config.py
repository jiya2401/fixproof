from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="development", alias="FIXPROOF_ENV")
    database_url: str = Field(default="sqlite:///./fixproof.db", alias="FIXPROOF_DATABASE_URL")
    max_repair_iterations: int = Field(default=3, alias="FIXPROOF_MAX_REPAIR_ITERATIONS")
    sandbox_mode: str = Field(default="docker", alias="FIXPROOF_SANDBOX_MODE")
    cors_origins: str = Field(default="http://localhost:5173", alias="FIXPROOF_CORS_ORIGINS")
    allow_unsafe_local_execution: bool = Field(
        default=False, alias="FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION"
    )

    nebius_api_key: str | None = Field(default=None, alias="NEBIUS_API_KEY")
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.nebius.com/v1", alias="NEBIUS_BASE_URL"
    )
    nebius_model: str = Field(
        default="nvidia/Nemotron-3_5-Lightning", alias="NEBIUS_MODEL"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
