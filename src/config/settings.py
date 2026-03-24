from functools import lru_cache

from dotenv import find_dotenv, load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(find_dotenv(usecwd=True), override=False)


class Settings(BaseSettings):
    app_name: str = "python-claw-gateway"
    database_url: str = "postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant"
    dedupe_retention_days: int = 30
    dedupe_stale_after_seconds: int = 300
    messages_page_default_limit: int = 50
    messages_page_max_limit: int = 100
    default_agent_id: str = "default-agent"
    runtime_transcript_context_limit: int = 20
    execution_run_lease_seconds: int = 60
    execution_run_max_attempts: int = 5
    execution_run_backoff_seconds: int = 5
    execution_run_backoff_max_seconds: int = 300
    execution_run_global_concurrency: int = 4
    session_runs_page_default_limit: int = 20
    session_runs_page_max_limit: int = 50

    model_config = SettingsConfigDict(
        env_prefix="PYTHON_CLAW_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
