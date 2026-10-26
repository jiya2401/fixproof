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
    sandbox_image: str = Field(default="fixproof-sandbox:latest", alias="FIXPROOF_SANDBOX_IMAGE")
    cors_origins: str = Field(default="http://localhost:5173", alias="FIXPROOF_CORS_ORIGINS")
    projects_dir: str = Field(default="./.fixproof_projects", alias="FIXPROOF_PROJECTS_DIR")
    # Comma-separated absolute folders the server may copy projects from. Empty = local paths off.
    local_path_roots: str = Field(default="", alias="FIXPROOF_LOCAL_PATH_ROOTS")
    max_project_mb: int = Field(default=50, alias="FIXPROOF_MAX_PROJECT_MB")
    allow_unsafe_local_execution: bool = Field(
        default=False, alias="FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION"
    )

    nebius_api_key: str | None = Field(default=None, alias="NEBIUS_API_KEY")
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.nebius.com/v1", alias="NEBIUS_BASE_URL"
    )
    # Unverified default: take the exact id from `python scripts/check_nebius.py`.
    nebius_model: str = Field(default="nvidia/nemotron-3-super-120b-a12b", alias="NEBIUS_MODEL")
    llm_timeout_seconds: float = Field(default=120.0, alias="FIXPROOF_LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="FIXPROOF_LLM_MAX_RETRIES")

    @property
    def local_path_root_list(self) -> list[str]:
        return [item.strip() for item in self.local_path_roots.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
