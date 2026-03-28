from functools import lru_cache
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(find_dotenv(usecwd=True), override=False)


class ChannelAccountConfig(BaseModel):
    channel_account_id: str
    channel_kind: Literal["slack", "telegram", "webchat"]
    mode: Literal["fake", "real"] = "fake"
    outbound_token: str | None = None
    signing_secret: str | None = None
    verification_token: str | None = None
    webhook_secret: str | None = None
    base_url: str | None = None
    transport_policy_id: str | None = None
    webchat_client_token: str | None = None

    @model_validator(mode="after")
    def validate_required_credentials(self) -> "ChannelAccountConfig":
        self.channel_account_id = self.channel_account_id.strip()
        if not self.channel_account_id:
            raise ValueError("channel_account_id must not be empty")
        if self.mode == "fake":
            return self
        if self.channel_kind == "slack":
            if not self.outbound_token or not self.signing_secret:
                raise ValueError("real slack accounts require outbound_token and signing_secret")
        elif self.channel_kind == "telegram":
            if not self.outbound_token or not self.webhook_secret:
                raise ValueError("real telegram accounts require outbound_token and webhook_secret")
        elif self.channel_kind == "webchat":
            if not self.webchat_client_token:
                raise ValueError("real webchat accounts require webchat_client_token")
        return self


def _default_channel_accounts() -> list[ChannelAccountConfig]:
    account_ids = ("acct", "acct-1")
    channel_kinds = ("slack", "telegram", "webchat")
    return [
        ChannelAccountConfig(channel_account_id=account_id, channel_kind=channel_kind, mode="fake")
        for account_id in account_ids
        for channel_kind in channel_kinds
    ]


class Settings(BaseSettings):
    _channel_account_lookup: dict[tuple[str, str], ChannelAccountConfig] = PrivateAttr(default_factory=dict)

    app_name: str = "python-claw-gateway"
    database_url: str = "postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant"
    dedupe_retention_days: int = 30
    dedupe_stale_after_seconds: int = 300
    messages_page_default_limit: int = 50
    messages_page_max_limit: int = 100
    default_agent_id: str = "default-agent"
    runtime_transcript_context_limit: int = 20
    runtime_mode: str = "rule_based"
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 1
    llm_temperature: float = 0.2
    llm_max_output_tokens: int | None = 512
    llm_tool_call_mode: str = "auto"
    llm_max_tool_requests_per_turn: int = 4
    llm_disable_tools: bool = False
    runtime_streaming_enabled: bool = True
    runtime_streaming_chunk_chars: int = 24
    webchat_sse_enabled: bool = True
    webchat_sse_replay_limit: int = 100
    execution_run_lease_seconds: int = 60
    execution_run_max_attempts: int = 5
    execution_run_backoff_seconds: int = 5
    execution_run_backoff_max_seconds: int = 300
    execution_run_global_concurrency: int = 4
    session_runs_page_default_limit: int = 20
    session_runs_page_max_limit: int = 50
    inbound_attachment_max_metadata_chars: int = 2000
    media_storage_root: str = ".claw-media"
    media_storage_bucket: str = "local-media"
    media_retention_days: int = 30
    media_allowed_schemes: str = "file,https"
    media_allowed_mime_prefixes: str = "image/,audio/,text/,application/pdf"
    media_max_bytes: int = 5242880
    retrieval_enabled: bool = True
    retrieval_strategy_id: str = "lexical-v1"
    retrieval_total_items: int = 4
    retrieval_memory_items: int = 2
    retrieval_attachment_items: int = 2
    retrieval_other_items: int = 2
    retrieval_chunk_chars: int = 280
    retrieval_min_score: float = 1.0
    memory_enabled: bool = True
    memory_strategy_id: str = "memory-v1"
    attachment_extraction_enabled: bool = True
    attachment_extraction_strategy_id: str = "attachment-v1"
    attachment_same_run_fast_path_enabled: bool = True
    attachment_same_run_max_bytes: int = 262144
    attachment_same_run_pdf_page_limit: int = 5
    attachment_same_run_timeout_seconds: int = 2
    remote_execution_enabled: bool = False
    node_runner_signing_key_id: str = "local-dev"
    node_runner_signing_secret: str = "local-dev-secret"
    node_runner_request_ttl_seconds: int = 30
    node_runner_timeout_ceiling_seconds: int = 30
    node_runner_allow_off_mode: bool = False
    node_runner_allowed_executables: str = "/bin/echo,/usr/bin/env"
    sandbox_workspace_root: str = ".claw-sandboxes"
    sandbox_shared_base_key: str = "shared-default"
    observability_json_logs: bool = True
    observability_log_content_preview: bool = False
    observability_log_content_preview_chars: int = 160
    diagnostics_enabled: bool = True
    diagnostics_page_default_limit: int = 20
    diagnostics_page_max_limit: int = 50
    diagnostics_admin_bearer_token: str | None = None
    diagnostics_internal_service_token: str | None = None
    health_ready_requires_auth: bool = True
    observability_metrics_enabled: bool = False
    observability_metrics_path: str = "/metrics"
    observability_tracing_enabled: bool = False
    execution_run_stale_after_seconds: int = 300
    outbox_job_stale_after_seconds: int = 300
    scheduled_job_fire_stale_after_seconds: int = 300
    outbound_delivery_stale_after_seconds: int = 300
    node_execution_stale_after_seconds: int = 300
    attachment_stale_after_seconds: int = 300
    channel_accounts: list[ChannelAccountConfig] = Field(default_factory=_default_channel_accounts)

    model_config = SettingsConfigDict(
        env_prefix="PYTHON_CLAW_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> "Settings":
        if self.runtime_mode not in {"rule_based", "provider"}:
            raise ValueError("runtime_mode must be one of: rule_based, provider")
        if self.llm_tool_call_mode not in {"auto", "none"}:
            raise ValueError("llm_tool_call_mode must be one of: auto, none")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_seconds must be greater than 0")
        if self.llm_max_retries < 0:
            raise ValueError("llm_max_retries must be greater than or equal to 0")
        if self.llm_max_tool_requests_per_turn <= 0:
            raise ValueError("llm_max_tool_requests_per_turn must be greater than 0")
        if self.runtime_streaming_chunk_chars <= 0:
            raise ValueError("runtime_streaming_chunk_chars must be greater than 0")
        if self.webchat_sse_replay_limit <= 0:
            raise ValueError("webchat_sse_replay_limit must be greater than 0")
        if self.llm_max_output_tokens is not None and self.llm_max_output_tokens <= 0:
            raise ValueError("llm_max_output_tokens must be greater than 0 when set")
        if self.runtime_mode == "provider" and not self.llm_api_key:
            raise ValueError("llm_api_key is required when runtime_mode=provider")
        if not self.retrieval_strategy_id.strip():
            raise ValueError("retrieval_strategy_id must not be empty")
        if not self.memory_strategy_id.strip():
            raise ValueError("memory_strategy_id must not be empty")
        if not self.attachment_extraction_strategy_id.strip():
            raise ValueError("attachment_extraction_strategy_id must not be empty")
        if self.retrieval_total_items < 0:
            raise ValueError("retrieval_total_items must be greater than or equal to 0")
        if self.retrieval_memory_items < 0 or self.retrieval_attachment_items < 0 or self.retrieval_other_items < 0:
            raise ValueError("retrieval per-source caps must be greater than or equal to 0")
        if (
            self.retrieval_memory_items + self.retrieval_attachment_items + self.retrieval_other_items
            < self.retrieval_total_items
        ):
            raise ValueError("retrieval per-source caps must cover retrieval_total_items")
        if self.retrieval_chunk_chars <= 0:
            raise ValueError("retrieval_chunk_chars must be greater than 0")
        if self.attachment_same_run_max_bytes <= 0:
            raise ValueError("attachment_same_run_max_bytes must be greater than 0")
        if self.attachment_same_run_pdf_page_limit <= 0:
            raise ValueError("attachment_same_run_pdf_page_limit must be greater than 0")
        if self.attachment_same_run_timeout_seconds <= 0:
            raise ValueError("attachment_same_run_timeout_seconds must be greater than 0")
        if self.attachment_same_run_fast_path_enabled and not self.attachment_extraction_enabled:
            raise ValueError("attachment extraction must be enabled when same-run fast path is enabled")
        lookup: dict[tuple[str, str], ChannelAccountConfig] = {}
        for account in self.channel_accounts:
            key = (account.channel_kind, account.channel_account_id)
            if key in lookup:
                raise ValueError(f"duplicate channel account configured for {account.channel_kind}:{account.channel_account_id}")
            lookup[key] = account
        self._channel_account_lookup = lookup
        return self

    def get_channel_account(self, *, channel_kind: str, channel_account_id: str) -> ChannelAccountConfig:
        key = (channel_kind.strip(), channel_account_id.strip())
        account = self._channel_account_lookup.get(key)
        if account is None:
            raise ValueError(f"channel account not configured for {key[0]}:{key[1]}")
        return account


@lru_cache
def get_settings() -> Settings:
    return Settings()
