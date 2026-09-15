"""Typed runtime configuration for ADCS services."""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_MCP_REVISION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class EnvironmentProfile(StrEnum):
    """Supported runtime environment profiles."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class LogLevel(StrEnum):
    """Allowed runtime log levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AbuseGuardMode(StrEnum):
    """Abuse guard policy mode."""

    OBSERVE_ONLY = "observe-only"
    ENFORCE = "enforce"


class AdminKeysSource(StrEnum):
    """Source for admin keys."""

    ENV = "env"
    JSON_DEV = "json_dev"


class PersistenceBackend(StrEnum):
    """Persistence adapter backend selection."""

    AUTO = "auto"
    MEMORY = "memory"
    POSTGRES = "postgres"


class RetrievalBackend(StrEnum):
    """Retrieval adapter backend selection."""

    AUTO = "auto"
    MEMORY = "memory"
    QDRANT_OPENSEARCH = "qdrant_opensearch"


class RerankerBackend(StrEnum):
    """Second-stage reranker backend selection."""

    DETERMINISTIC = "deterministic"
    ADVANCED_HEURISTIC = "advanced_heuristic"
    OPENAI_COMPATIBLE = "openai_compatible"


class EmbeddingBackend(StrEnum):
    """Embedding provider backend selection."""

    DETERMINISTIC = "deterministic"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


class QualityGatePhase(StrEnum):
    """Quality-gate enforcement phase."""

    MVP = "mvp"
    PREPROD = "preprod"
    GA = "ga"


class WorkerExecutionMode(StrEnum):
    """Background task execution mode."""

    AUTO = "auto"
    INLINE = "inline"
    CELERY = "celery"


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    env_profile: EnvironmentProfile = Field(default=EnvironmentProfile.DEV, alias="ADCS_ENV")
    log_level: LogLevel = Field(default=LogLevel.INFO, alias="ADCS_LOG_LEVEL")

    host: str = Field(default="0.0.0.0", alias="ADCS_HOST")
    port: int = Field(default=8080, ge=1, le=65535, alias="ADCS_PORT")

    admin_api_key: SecretStr = Field(default=SecretStr("replace-me"), alias="ADCS_API_KEY")
    # Key for the HMAC pseudonyms ip_hash and query_fingerprint (see
    # docs/data-protection-and-pii.md). Empty means unkeyed SHA-256, which for an
    # IPv4 address is a reversible encoding rather than a pseudonym — hence the
    # prod/staging guard below.
    hash_secret: SecretStr = Field(default=SecretStr(""), alias="ADCS_HASH_SECRET")
    admin_keys_source: AdminKeysSource = Field(
        default=AdminKeysSource.ENV,
        alias="ADCS_ADMIN_KEYS_SOURCE",
    )
    admin_keys_json_path: Path = Field(
        default=Path("config/admin_keys.json"),
        alias="ADCS_ADMIN_KEYS_JSON_PATH",
    )
    admin_session_cookie_name: str = Field(
        default="adcs_admin_session",
        alias="ADCS_ADMIN_SESSION_COOKIE_NAME",
    )
    admin_session_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        ge=300,
        le=365 * 24 * 60 * 60,
        alias="ADCS_ADMIN_SESSION_TTL_SECONDS",
    )
    admin_session_remember_ttl_seconds: int = Field(
        default=180 * 24 * 60 * 60,
        ge=3600,
        le=365 * 24 * 60 * 60,
        alias="ADCS_ADMIN_SESSION_REMEMBER_TTL_SECONDS",
    )
    admin_session_cookie_secure: bool = Field(
        default=False,
        alias="ADCS_ADMIN_SESSION_COOKIE_SECURE",
    )
    admin_session_cookie_samesite: str = Field(
        default="lax",
        alias="ADCS_ADMIN_SESSION_COOKIE_SAMESITE",
    )

    postgres_dsn: str = Field(
        default="postgresql+psycopg://adcs:adcs@localhost:5432/adcs",
        alias="POSTGRES_DSN",
    )
    # Serve API Reference from the Postgres structured symbol store
    # (ADR-011) rather than dense vectors. Opt-in while the legacy
    # apiref_dense_v1 path is still supported.
    apiref_structured_store_enabled: bool = Field(
        default=False,
        alias="APIREF_STRUCTURED_STORE_ENABLED",
    )
    # Embed only English documentation chunks into the vector/lexical indexes.
    # All locales are still parsed to the staging store; only the
    # English subset is embedded, matching the EN-only v1 release scope. Opt-in
    # so multi-locale environments keep current behaviour.
    docs_english_only_embed: bool = Field(
        default=False,
        alias="DOCS_ENGLISH_ONLY_EMBED",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        alias="RABBITMQ_URL",
    )
    # Number of trusted reverse proxies in front of the API. Behind the nginx
    # ingress every request arrives from the proxy's address, so keying the abuse
    # guard on the socket peer puts all callers in a single bucket — enforce mode
    # would then throttle the whole public API at one client's limit. With N > 0
    # the client is read from the X-Forwarded-For chain at position -(N+1); it
    # stays 0 by default because trusting that header without
    # a proxy in front lets any caller forge its own identity.
    trusted_proxy_hops: int = Field(
        default=0,
        ge=0,
        le=8,
        alias="ADCS_TRUSTED_PROXY_HOPS",
    )
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    # Accept both DOCS_VECTOR_COLLECTION and ADCS_DOCS_VECTOR_COLLECTION. With a
    # single unprefixed alias the prefixed variable would be silently discarded
    # (model config uses extra="ignore"), so the value an operator set would not
    # be the value the service uses.
    docs_vector_collection: str = Field(
        default="docs_dense_en_v1",
        validation_alias=AliasChoices("DOCS_VECTOR_COLLECTION", "ADCS_DOCS_VECTOR_COLLECTION"),
    )
    apiref_vector_collection: str = Field(
        default="apiref_dense_v1",
        validation_alias=AliasChoices("APIREF_VECTOR_COLLECTION", "ADCS_APIREF_VECTOR_COLLECTION"),
    )
    opensearch_url: str = Field(default="http://localhost:9200", alias="OPENSEARCH_URL")
    persistence_backend: PersistenceBackend = Field(
        default=PersistenceBackend.AUTO,
        alias="ADCS_PERSISTENCE_BACKEND",
    )
    retrieval_backend: RetrievalBackend = Field(
        default=RetrievalBackend.AUTO,
        alias="ADCS_RETRIEVAL_BACKEND",
    )
    reranker_backend: RerankerBackend = Field(
        default=RerankerBackend.ADVANCED_HEURISTIC,
        alias="ADCS_RERANKER_BACKEND",
    )
    embedding_backend: EmbeddingBackend = Field(
        default=EmbeddingBackend.DETERMINISTIC,
        alias="ADCS_EMBEDDING_BACKEND",
    )
    embedding_model: str = Field(
        default="nomic-embed-text",
        alias="ADCS_EMBEDDING_MODEL",
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_URL",
    )
    embedding_api_url: str = Field(
        default="http://localhost:11434/v1",
        alias="ADCS_EMBEDDING_API_URL",
    )
    embedding_api_key: str = Field(
        default="",
        alias="ADCS_EMBEDDING_API_KEY",
    )
    hybrid_dense_weight: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        alias="ADCS_HYBRID_DENSE_WEIGHT",
    )
    hybrid_lexical_weight: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        alias="ADCS_HYBRID_LEXICAL_WEIGHT",
    )
    hybrid_lane_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        le=60.0,
        alias="ADCS_HYBRID_LANE_TIMEOUT_SECONDS",
    )
    endpoint_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=120.0,
        alias="ADCS_ENDPOINT_TIMEOUT_SECONDS",
    )
    test_mode: bool = Field(default=False, alias="ADCS_TEST_MODE")

    api_docs_enabled: bool = Field(default=False, alias="ADCS_API_DOCS_ENABLED")
    webmcp_enabled: bool = Field(default=False, alias="ADCS_WEBMCP_ENABLED")
    webmcp_confirmation_ttl_seconds: int = Field(
        default=300,
        ge=1,
        le=3600,
        alias="ADCS_WEBMCP_CONFIRM_TTL_SECONDS",
    )
    mcp_supported_revisions: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("2025-11-25", "2025-06-18", "2024-11-05"),
        alias="ADCS_MCP_SUPPORTED_REVISIONS",
    )

    abuse_guard_mode: AbuseGuardMode = Field(
        default=AbuseGuardMode.OBSERVE_ONLY,
        alias="ADCS_ABUSE_GUARD_MODE",
    )
    abuse_guard_allowlist: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(),
        alias="ADCS_ABUSE_GUARD_ALLOWLIST",
    )
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:3000", "http://127.0.0.1:3000"),
        alias="ADCS_CORS_ALLOW_ORIGINS",
    )
    abuse_requests_per_ip_per_minute: int = Field(
        default=120,
        ge=1,
        alias="ADCS_ABUSE_REQUESTS_PER_IP_PER_MINUTE",
    )
    abuse_requests_per_fingerprint_per_minute: int = Field(
        default=180,
        ge=1,
        alias="ADCS_ABUSE_REQUESTS_PER_FINGERPRINT_PER_MINUTE",
    )
    abuse_requests_global_per_minute: int = Field(
        default=5000,
        ge=1,
        alias="ADCS_ABUSE_REQUESTS_GLOBAL_PER_MINUTE",
    )
    ingestion_partial_publish_threshold_pct: int = Field(
        default=30,
        ge=0,
        le=100,
        alias="ADCS_INGESTION_PARTIAL_PUBLISH_THRESHOLD_PCT",
    )
    ingestion_publish_safety_min_coverage_pct: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        alias="ADCS_INGESTION_PUBLISH_SAFETY_MIN_COVERAGE_PCT",
    )
    ingestion_metadata_quarantine_policy: str = Field(
        default="best_effort_continue",
        alias="ADCS_INGESTION_METADATA_QUARANTINE_POLICY",
    )
    ingestion_retry_max_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        alias="ADCS_INGESTION_RETRY_MAX_ATTEMPTS",
    )
    ingestion_retry_backoff_base_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
        alias="ADCS_INGESTION_RETRY_BACKOFF_BASE_SECONDS",
    )
    ingestion_retry_backoff_max_seconds: int = Field(
        default=120,
        ge=1,
        le=3600,
        alias="ADCS_INGESTION_RETRY_BACKOFF_MAX_SECONDS",
    )
    translation_llm_config_path: Path = Field(
        default=Path("config/translation_llm.json"),
        alias="ADCS_TRANSLATION_LLM_CONFIG_PATH",
    )
    release_catalog_config_path: Path = Field(
        default=Path("config/release_catalog.json"),
        alias="ADCS_RELEASE_CATALOG_CONFIG_PATH",
    )
    ingestion_llm_policy_config_path: Path = Field(
        default=Path("config/ingestion_llm_policy.json"),
        alias="ADCS_INGESTION_LLM_POLICY_CONFIG_PATH",
    )
    ingestion_prompt_registry_config_path: Path = Field(
        default=Path("config/ingestion_prompt_registry.json"),
        alias="ADCS_INGESTION_PROMPT_REGISTRY_CONFIG_PATH",
    )
    index_topology_policy_config_path: Path = Field(
        default=Path("config/index-topology-policy.json"),
        alias="ADCS_INDEX_TOPOLOGY_POLICY_CONFIG_PATH",
    )
    howto_override_store_path: Path = Field(
        default=Path("artifacts/howto/overrides.json"),
        alias="ADCS_HOWTO_OVERRIDE_STORE_PATH",
    )
    howto_asset_root: Path = Field(
        default=Path("artifacts/howto/assets"),
        alias="ADCS_HOWTO_ASSET_ROOT",
    )
    layout_detection_confidence_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        alias="ADCS_LAYOUT_DETECTION_CONFIDENCE_THRESHOLD",
    )
    layout_detection_allow_manual_override: bool = Field(
        default=True,
        alias="ADCS_LAYOUT_DETECTION_ALLOW_MANUAL_OVERRIDE",
    )
    quality_gate_phase: QualityGatePhase = Field(
        default=QualityGatePhase.MVP,
        alias="ADCS_QUALITY_GATES_PHASE",
    )
    tracing_enabled: bool = Field(default=False, alias="ADCS_TRACING_ENABLED")
    tracing_service_name: str = Field(
        default="adcs-api",
        alias="ADCS_TRACING_SERVICE_NAME",
    )
    tracing_sample_ratio: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        alias="ADCS_TRACING_SAMPLE_RATIO",
    )
    tracing_error_sample_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        alias="ADCS_TRACING_ERROR_SAMPLE_RATIO",
    )
    tracing_slow_request_threshold_ms: int = Field(
        default=1200,
        ge=1,
        le=60_000,
        alias="ADCS_TRACING_SLOW_REQUEST_THRESHOLD_MS",
    )
    tracing_otlp_endpoint: str | None = Field(
        default=None,
        alias="ADCS_TRACING_OTLP_ENDPOINT",
    )
    worker_execution_mode: WorkerExecutionMode = Field(
        default=WorkerExecutionMode.AUTO,
        alias="ADCS_WORKER_EXECUTION_MODE",
    )
    operation_state_root: Path = Field(
        default=Path("artifacts/runtime-state"),
        alias="ADCS_OPERATION_STATE_ROOT",
    )
    observability_control_plane_config_path: Path = Field(
        default=Path("config/observability-control-plane.json"),
        alias="ADCS_OBSERVABILITY_CONTROL_PLANE_CONFIG_PATH",
    )
    canary_policy_config_path: Path = Field(
        default=Path("config/canary-policy.json"),
        alias="ADCS_CANARY_POLICY_CONFIG_PATH",
    )
    deploy_smoke_report_path: Path = Field(
        default=Path("reports/deploy/smoke-report.json"),
        alias="ADCS_DEPLOY_SMOKE_REPORT_PATH",
    )
    canary_evaluation_report_path: Path = Field(
        default=Path("reports/deploy/canary-evaluation.json"),
        alias="ADCS_CANARY_EVALUATION_REPORT_PATH",
    )

    @field_validator(
        "mcp_supported_revisions",
        "abuse_guard_allowlist",
        "cors_allow_origins",
        mode="before",
    )
    @classmethod
    def _parse_csv_values(cls, raw_value: object) -> tuple[str, ...] | object:
        if raw_value is None:
            return ()

        if isinstance(raw_value, str):
            return tuple(part.strip() for part in raw_value.split(",") if part.strip())

        if isinstance(raw_value, (tuple, list, set)):
            return tuple(str(item).strip() for item in raw_value if str(item).strip())

        return raw_value

    @field_validator("mcp_supported_revisions")
    @classmethod
    def _validate_mcp_supported_revisions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            msg = "At least one MCP revision is required."
            raise ValueError(msg)

        invalid_revisions = tuple(
            revision for revision in value if not _MCP_REVISION_PATTERN.match(revision)
        )
        if invalid_revisions:
            msg = "MCP revisions must use YYYY-MM-DD format."
            raise ValueError(msg)

        return value

    @field_validator("ingestion_metadata_quarantine_policy")
    @classmethod
    def _validate_ingestion_metadata_quarantine_policy(cls, value: str) -> str:
        normalized = value.strip().casefold().replace("-", "_")
        if normalized not in {"best_effort_continue", "strict_block"}:
            msg = (
                "ADCS_INGESTION_METADATA_QUARANTINE_POLICY must be one of "
                "`best_effort_continue` or `strict_block`."
            )
            raise ValueError(msg)
        return normalized

    @field_validator("admin_session_cookie_name")
    @classmethod
    def _validate_admin_session_cookie_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "ADCS_ADMIN_SESSION_COOKIE_NAME must not be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("admin_session_cookie_samesite")
    @classmethod
    def _validate_admin_session_cookie_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            msg = "ADCS_ADMIN_SESSION_COOKIE_SAMESITE must be one of `lax`, `strict`, or `none`."
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _validate_profile_constraints(self) -> Settings:
        if (
            self.admin_keys_source is AdminKeysSource.JSON_DEV
            and self.env_profile is not EnvironmentProfile.DEV
        ):
            msg = "ADCS_ADMIN_KEYS_SOURCE=json_dev is allowed only for ADCS_ENV=dev."
            raise ValueError(msg)

        if self.env_profile in {EnvironmentProfile.STAGING, EnvironmentProfile.PROD}:
            if self.admin_api_key.get_secret_value().strip() == "replace-me":
                msg = "ADCS_API_KEY placeholder is not allowed for staging/prod profiles."
                raise ValueError(msg)
            if not self.hash_secret.get_secret_value().strip():
                msg = (
                    "ADCS_HASH_SECRET is required for staging/prod profiles: without it "
                    "ip_hash and query_fingerprint fall back to unkeyed SHA-256, which is "
                    "reversible for an IPv4 keyspace (see docs/data-protection-and-pii.md)."
                )
                raise ValueError(msg)
        if self.ingestion_retry_backoff_max_seconds < self.ingestion_retry_backoff_base_seconds:
            msg = (
                "ADCS_INGESTION_RETRY_BACKOFF_MAX_SECONDS must be >= "
                "ADCS_INGESTION_RETRY_BACKOFF_BASE_SECONDS."
            )
            raise ValueError(msg)
        if self.admin_session_cookie_samesite == "none" and not self.admin_session_cookie_secure:
            msg = (
                "ADCS_ADMIN_SESSION_COOKIE_SECURE must be true when "
                "ADCS_ADMIN_SESSION_COOKIE_SAMESITE=none."
            )
            raise ValueError(msg)
        if self.admin_session_remember_ttl_seconds < self.admin_session_ttl_seconds:
            msg = (
                "ADCS_ADMIN_SESSION_REMEMBER_TTL_SECONDS must be >= ADCS_ADMIN_SESSION_TTL_SECONDS."
            )
            raise ValueError(msg)

        # Production guards: require remote embedding and live retrieval backend
        if self.env_profile is EnvironmentProfile.PROD:
            if self.embedding_backend is EmbeddingBackend.DETERMINISTIC:
                msg = "ADCS_EMBEDDING_BACKEND=deterministic is not allowed for prod profile."
                raise ValueError(msg)
            if not self.embedding_api_url:
                msg = "ADCS_EMBEDDING_API_URL must be set for prod profile."
                raise ValueError(msg)
            if self.retrieval_backend is RetrievalBackend.MEMORY:
                msg = (
                    "ADCS_RETRIEVAL_BACKEND=memory is not allowed for prod profile. "
                    "Use qdrant_opensearch."
                )
                raise ValueError(msg)
            if not self.qdrant_url:
                msg = "ADCS_QDRANT_URL must be set for prod profile."
                raise ValueError(msg)
            if "adcs:adcs@" in self.postgres_dsn or "replace-me" in self.postgres_dsn:
                msg = (
                    "POSTGRES_DSN must use real credentials for prod profile "
                    "(the adcs:adcs default or a replace-me placeholder is not allowed)."
                )
                raise ValueError(msg)
            if "guest:guest@" in self.rabbitmq_url or "replace-me" in self.rabbitmq_url:
                msg = (
                    "RABBITMQ_URL must use real credentials for prod profile "
                    "(the guest:guest default or a replace-me placeholder is not allowed)."
                )
                raise ValueError(msg)

        return self

    def safe_summary(self) -> dict[str, object]:
        """Return a redacted settings summary suitable for logs."""
        return {
            "env_profile": self.env_profile.value,
            "log_level": self.log_level.value,
            "host": self.host,
            "port": self.port,
            "admin_keys_source": self.admin_keys_source.value,
            "admin_api_key": "********",
            "admin_session_cookie_name": self.admin_session_cookie_name,
            "admin_session_ttl_seconds": self.admin_session_ttl_seconds,
            "admin_session_remember_ttl_seconds": self.admin_session_remember_ttl_seconds,
            "admin_session_cookie_secure": self.admin_session_cookie_secure,
            "admin_session_cookie_samesite": self.admin_session_cookie_samesite,
            "abuse_guard_mode": self.abuse_guard_mode.value,
            "abuse_guard_allowlist_size": len(self.abuse_guard_allowlist),
            "cors_allow_origins": list(self.cors_allow_origins),
            "ingestion_partial_publish_threshold_pct": self.ingestion_partial_publish_threshold_pct,
            "ingestion_publish_safety_min_coverage_pct": (
                self.ingestion_publish_safety_min_coverage_pct
            ),
            "ingestion_metadata_quarantine_policy": (self.ingestion_metadata_quarantine_policy),
            "ingestion_retry_max_attempts": self.ingestion_retry_max_attempts,
            "ingestion_retry_backoff_base_seconds": (self.ingestion_retry_backoff_base_seconds),
            "ingestion_retry_backoff_max_seconds": self.ingestion_retry_backoff_max_seconds,
            "translation_llm_config_path": str(self.translation_llm_config_path),
            "release_catalog_config_path": str(self.release_catalog_config_path),
            "ingestion_llm_policy_config_path": str(self.ingestion_llm_policy_config_path),
            "ingestion_prompt_registry_config_path": str(
                self.ingestion_prompt_registry_config_path
            ),
            "index_topology_policy_config_path": str(self.index_topology_policy_config_path),
            "howto_override_store_path": str(self.howto_override_store_path),
            "howto_asset_root": str(self.howto_asset_root),
            "layout_detection_confidence_threshold": self.layout_detection_confidence_threshold,
            "layout_detection_allow_manual_override": (self.layout_detection_allow_manual_override),
            "quality_gate_phase": self.quality_gate_phase.value,
            "tracing_enabled": self.tracing_enabled,
            "tracing_service_name": self.tracing_service_name,
            "tracing_sample_ratio": self.tracing_sample_ratio,
            "tracing_error_sample_ratio": self.tracing_error_sample_ratio,
            "tracing_slow_request_threshold_ms": self.tracing_slow_request_threshold_ms,
            "tracing_otlp_endpoint": self.tracing_otlp_endpoint,
            "worker_execution_mode": self.worker_execution_mode.value,
            "operation_state_root": str(self.operation_state_root),
            "observability_control_plane_config_path": str(
                self.observability_control_plane_config_path
            ),
            "canary_policy_config_path": str(self.canary_policy_config_path),
            "deploy_smoke_report_path": str(self.deploy_smoke_report_path),
            "canary_evaluation_report_path": str(self.canary_evaluation_report_path),
            "persistence_backend": self.persistence_backend.value,
            "retrieval_backend": self.retrieval_backend.value,
            "reranker_backend": self.reranker_backend.value,
            "embedding_backend": self.embedding_backend.value,
            "embedding_model": self.embedding_model,
            "ollama_url": self.ollama_url,
            "embedding_api_url": self.embedding_api_url,
            "test_mode": self.test_mode,
            "webmcp_enabled": self.webmcp_enabled,
            "webmcp_confirmation_ttl_seconds": self.webmcp_confirmation_ttl_seconds,
            "mcp_supported_revisions": list(self.mcp_supported_revisions),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached runtime settings."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached runtime settings for tests and reloads."""
    get_settings.cache_clear()
