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


class PolicyProfileConfig(BaseModel):
    key: str
    remote_execution_enabled: bool = False
    denied_capability_names: list[str] = Field(default_factory=list)
    delegation_enabled: bool = False
    max_delegation_depth: int = 0
    allowed_child_agent_ids: list[str] = Field(default_factory=list)
    max_active_delegations_per_run: int | None = None
    max_active_delegations_per_session: int | None = None

    @model_validator(mode="after")
    def validate_policy_profile(self) -> "PolicyProfileConfig":
        self.key = self.key.strip()
        if not self.key:
            raise ValueError("policy profile key must not be empty")
        self.denied_capability_names = sorted({item.strip() for item in self.denied_capability_names if item.strip()})
        self.allowed_child_agent_ids = sorted({item.strip() for item in self.allowed_child_agent_ids if item.strip()})
        if self.max_delegation_depth < 0:
            raise ValueError("max_delegation_depth must be greater than or equal to 0")
        if self.max_active_delegations_per_run is not None and self.max_active_delegations_per_run <= 0:
            raise ValueError("max_active_delegations_per_run must be greater than 0 when set")
        if self.max_active_delegations_per_session is not None and self.max_active_delegations_per_session <= 0:
            raise ValueError("max_active_delegations_per_session must be greater than 0 when set")
        return self


class ToolProfileConfig(BaseModel):
    key: str
    allowed_capability_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_profile(self) -> "ToolProfileConfig":
        self.key = self.key.strip()
        if not self.key:
            raise ValueError("tool profile key must not be empty")
        self.allowed_capability_names = sorted({item.strip() for item in self.allowed_capability_names if item.strip()})
        if not self.allowed_capability_names:
            raise ValueError("tool profile allowed_capability_names must not be empty")
        return self


class HistoricalAgentProfileOverrideConfig(BaseModel):
    agent_id: str
    model_profile_key: str = "default"
    policy_profile_key: str = "default"
    tool_profile_key: str = "default"

    @model_validator(mode="after")
    def validate_override(self) -> "HistoricalAgentProfileOverrideConfig":
        self.agent_id = self.agent_id.strip()
        if not self.agent_id:
            raise ValueError("historical agent override agent_id must not be empty")
        self.model_profile_key = self.model_profile_key.strip()
        self.policy_profile_key = self.policy_profile_key.strip()
        self.tool_profile_key = self.tool_profile_key.strip()
        if not self.model_profile_key or not self.policy_profile_key or not self.tool_profile_key:
            raise ValueError("historical agent override profile keys must not be empty")
        return self


def _default_channel_accounts() -> list[ChannelAccountConfig]:
    account_ids = ("acct", "acct-1")
    channel_kinds = ("slack", "telegram", "webchat")
    return [
        ChannelAccountConfig(channel_account_id=account_id, channel_kind=channel_kind, mode="fake")
        for account_id in account_ids
        for channel_kind in channel_kinds
    ]


def _default_policy_profiles() -> list[PolicyProfileConfig]:
    return [PolicyProfileConfig(key="default", remote_execution_enabled=False, denied_capability_names=[])]


def _default_tool_profiles() -> list[ToolProfileConfig]:
    return [
        ToolProfileConfig(
            key="default",
            allowed_capability_names=["echo_text", "remote_exec", "send_message"],
        )
    ]


class Settings(BaseSettings):
    _channel_account_lookup: dict[tuple[str, str], ChannelAccountConfig] = PrivateAttr(default_factory=dict)
    _policy_profile_lookup: dict[str, PolicyProfileConfig] = PrivateAttr(default_factory=dict)
    _tool_profile_lookup: dict[str, ToolProfileConfig] = PrivateAttr(default_factory=dict)
    _historical_agent_override_lookup: dict[str, HistoricalAgentProfileOverrideConfig] = PrivateAttr(default_factory=dict)

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
    delegation_package_transcript_turns: int = 6
    delegation_package_retrieval_items: int = 4
    delegation_package_attachment_items: int = 2
    delegation_package_max_chars: int = 4000
    remote_execution_enabled: bool = False
    node_runner_mode: Literal["in_process", "http"] = "in_process"
    node_runner_base_url: str | None = None
    node_runner_signing_key_id: str = "local-dev"
    node_runner_signing_secret: str = "local-dev-secret"
    node_runner_previous_signing_key_id: str | None = None
    node_runner_previous_signing_secret: str | None = None
    node_runner_request_ttl_seconds: int = 30
    node_runner_timeout_ceiling_seconds: int = 30
    node_runner_internal_bearer_token: str | None = None
    node_runner_previous_internal_bearer_token: str | None = None
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
    admin_reads_require_auth: bool = True
    diagnostics_require_auth: bool = True
    operator_auth_bearer_token: str | None = None
    previous_operator_auth_bearer_token: str | None = None
    internal_service_auth_token: str | None = None
    previous_internal_service_auth_token: str | None = None
    operator_principal_header_name: str = "X-Operator-Id"
    internal_service_principal_header_name: str = "X-Internal-Service-Principal"
    auth_fail_closed_in_production: bool = True
    default_assignment_queue_key: str = "default"
    approval_action_token_ttl_seconds: int = 3600
    slack_interactive_approvals_enabled: bool = False
    telegram_interactive_approvals_enabled: bool = False
    webchat_interactive_approvals_enabled: bool = False
    takeover_suppresses_inflight_dispatch: bool = True
    operator_note_max_chars: int = 2000
    health_ready_requires_auth: bool = True
    rate_limits_enabled: bool = False
    inbound_requests_per_minute_per_channel_account: int = 60
    admin_requests_per_minute_per_operator: int = 120
    approval_action_requests_per_minute_per_session: int = 30
    provider_tokens_per_hour_per_agent: int = 200000
    provider_requests_per_minute_per_model: int = 120
    quota_counter_retention_days: int = 7
    observability_metrics_enabled: bool = False
    observability_metrics_path: str = "/metrics"
    observability_tracing_enabled: bool = False
    provider_retry_base_seconds: float = 1.0
    provider_retry_max_seconds: float = 16.0
    provider_retry_jitter_seconds: float = 0.25
    execution_run_stale_after_seconds: int = 300
    outbox_job_stale_after_seconds: int = 300
    scheduled_job_fire_stale_after_seconds: int = 300
    outbound_delivery_stale_after_seconds: int = 300
    node_execution_stale_after_seconds: int = 300
    attachment_stale_after_seconds: int = 300
    channel_accounts: list[ChannelAccountConfig] = Field(default_factory=_default_channel_accounts)
    policy_profiles: list[PolicyProfileConfig] = Field(default_factory=_default_policy_profiles)
    tool_profiles: list[ToolProfileConfig] = Field(default_factory=_default_tool_profiles)
    historical_agent_profile_overrides: list[HistoricalAgentProfileOverrideConfig] = Field(default_factory=list)

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
        if self.node_runner_mode not in {"in_process", "http"}:
            raise ValueError("node_runner_mode must be one of: in_process, http")
        if self.node_runner_mode == "http" and not (self.node_runner_base_url or "").strip():
            raise ValueError("node_runner_base_url is required when node_runner_mode=http")
        if self.node_runner_mode == "http" and not self.node_runner_internal_bearer_token:
            raise ValueError("node_runner_internal_bearer_token is required when node_runner_mode=http")
        if self.webchat_sse_replay_limit <= 0:
            raise ValueError("webchat_sse_replay_limit must be greater than 0")
        if self.approval_action_token_ttl_seconds <= 0:
            raise ValueError("approval_action_token_ttl_seconds must be greater than 0")
        if self.operator_note_max_chars <= 0:
            raise ValueError("operator_note_max_chars must be greater than 0")
        if self.inbound_requests_per_minute_per_channel_account <= 0:
            raise ValueError("inbound_requests_per_minute_per_channel_account must be greater than 0")
        if self.admin_requests_per_minute_per_operator <= 0:
            raise ValueError("admin_requests_per_minute_per_operator must be greater than 0")
        if self.approval_action_requests_per_minute_per_session <= 0:
            raise ValueError("approval_action_requests_per_minute_per_session must be greater than 0")
        if self.provider_tokens_per_hour_per_agent <= 0:
            raise ValueError("provider_tokens_per_hour_per_agent must be greater than 0")
        if self.provider_requests_per_minute_per_model <= 0:
            raise ValueError("provider_requests_per_minute_per_model must be greater than 0")
        if self.quota_counter_retention_days <= 0:
            raise ValueError("quota_counter_retention_days must be greater than 0")
        if self.provider_retry_base_seconds <= 0:
            raise ValueError("provider_retry_base_seconds must be greater than 0")
        if self.provider_retry_max_seconds < self.provider_retry_base_seconds:
            raise ValueError("provider_retry_max_seconds must be greater than or equal to provider_retry_base_seconds")
        if self.provider_retry_jitter_seconds < 0:
            raise ValueError("provider_retry_jitter_seconds must be greater than or equal to 0")
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
        if not self.default_assignment_queue_key.strip():
            raise ValueError("default_assignment_queue_key must not be empty")
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
        if self.delegation_package_transcript_turns <= 0:
            raise ValueError("delegation_package_transcript_turns must be greater than 0")
        if self.delegation_package_retrieval_items <= 0:
            raise ValueError("delegation_package_retrieval_items must be greater than 0")
        if self.delegation_package_attachment_items <= 0:
            raise ValueError("delegation_package_attachment_items must be greater than 0")
        if self.delegation_package_max_chars <= 0:
            raise ValueError("delegation_package_max_chars must be greater than 0")
        lookup: dict[tuple[str, str], ChannelAccountConfig] = {}
        for account in self.channel_accounts:
            key = (account.channel_kind, account.channel_account_id)
            if key in lookup:
                raise ValueError(f"duplicate channel account configured for {account.channel_kind}:{account.channel_account_id}")
            lookup[key] = account
        self._channel_account_lookup = lookup
        policy_lookup: dict[str, PolicyProfileConfig] = {}
        for profile in self.policy_profiles:
            if profile.key in policy_lookup:
                raise ValueError(f"duplicate policy profile configured for {profile.key}")
            policy_lookup[profile.key] = profile
        tool_lookup: dict[str, ToolProfileConfig] = {}
        for profile in self.tool_profiles:
            if profile.key in tool_lookup:
                raise ValueError(f"duplicate tool profile configured for {profile.key}")
            tool_lookup[profile.key] = profile
        override_lookup: dict[str, HistoricalAgentProfileOverrideConfig] = {}
        for override in self.historical_agent_profile_overrides:
            if override.agent_id in override_lookup:
                raise ValueError(f"duplicate historical agent override configured for {override.agent_id}")
            if override.policy_profile_key not in policy_lookup:
                raise ValueError(f"unknown policy profile for historical override {override.agent_id}")
            if override.tool_profile_key not in tool_lookup:
                raise ValueError(f"unknown tool profile for historical override {override.agent_id}")
            override_lookup[override.agent_id] = override
        if "default" not in policy_lookup:
            raise ValueError("default policy profile must be configured")
        if "default" not in tool_lookup:
            raise ValueError("default tool profile must be configured")
        self._policy_profile_lookup = policy_lookup
        self._tool_profile_lookup = tool_lookup
        self._historical_agent_override_lookup = override_lookup
        return self

    @property
    def resolved_operator_auth_bearer_token(self) -> str | None:
        return self.operator_auth_bearer_token or self.diagnostics_admin_bearer_token

    @property
    def resolved_internal_service_auth_token(self) -> str | None:
        return self.internal_service_auth_token or self.diagnostics_internal_service_token

    def operator_auth_tokens(self) -> set[str]:
        return {
            token
            for token in {
                self.resolved_operator_auth_bearer_token,
                self.previous_operator_auth_bearer_token,
                self.diagnostics_admin_bearer_token,
            }
            if token
        }

    def internal_service_auth_tokens(self) -> set[str]:
        return {
            token
            for token in {
                self.resolved_internal_service_auth_token,
                self.previous_internal_service_auth_token,
                self.diagnostics_internal_service_token,
            }
            if token
        }

    def node_runner_transport_tokens(self) -> set[str]:
        return {
            token
            for token in {
                self.node_runner_internal_bearer_token,
                self.node_runner_previous_internal_bearer_token,
            }
            if token
        }

    def node_runner_signing_keys(self) -> dict[str, str]:
        keys = {self.node_runner_signing_key_id: self.node_runner_signing_secret}
        if self.node_runner_previous_signing_key_id and self.node_runner_previous_signing_secret:
            keys[self.node_runner_previous_signing_key_id] = self.node_runner_previous_signing_secret
        return keys

    def get_channel_account(self, *, channel_kind: str, channel_account_id: str) -> ChannelAccountConfig:
        key = (channel_kind.strip(), channel_account_id.strip())
        account = self._channel_account_lookup.get(key)
        if account is None:
            raise ValueError(f"channel account not configured for {key[0]}:{key[1]}")
        return account

    def get_policy_profile(self, key: str) -> PolicyProfileConfig:
        profile = self._policy_profile_lookup.get(key.strip())
        if profile is None:
            raise ValueError(f"policy profile not configured for {key.strip()}")
        return profile

    def get_tool_profile(self, key: str) -> ToolProfileConfig:
        profile = self._tool_profile_lookup.get(key.strip())
        if profile is None:
            raise ValueError(f"tool profile not configured for {key.strip()}")
        return profile

    def channel_supports_interactive_approvals(self, *, channel_kind: str) -> bool:
        if channel_kind == "slack":
            return self.slack_interactive_approvals_enabled
        if channel_kind == "telegram":
            return self.telegram_interactive_approvals_enabled
        if channel_kind == "webchat":
            return self.webchat_interactive_approvals_enabled
        return False

    def get_historical_agent_override(self, agent_id: str) -> HistoricalAgentProfileOverrideConfig | None:
        return self._historical_agent_override_lookup.get(agent_id.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
