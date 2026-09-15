"""Prompt registry and deterministic A/B assignment for Hugo conversion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from adcs.ingestion.llm_runtime_policy import IngestionLLMBackend


class PromptAssignmentUnit(StrEnum):
    """Supported assignment units for conversion experiments."""

    SOURCE_PATH = "source_path"


@dataclass(frozen=True, slots=True)
class ConversionPromptVariant:
    """One versioned prompt variant configuration."""

    variant_id: str
    weight_pct: int
    prompt_pack_version: str
    system_prompt_path: str
    user_base_prompt_path: str
    user_docs_prompt_path: str
    user_apiref_prompt_path: str
    backend_override: IngestionLLMBackend | None = None


@dataclass(frozen=True, slots=True)
class ConversionPromptAssignment:
    """Resolved prompt assignment for one source markdown file."""

    repo_id: str
    source_kind: str
    source_path: str
    variant_id: str
    prompt_pack_version: str
    system_prompt_path: str
    user_prompt_path: str
    backend: IngestionLLMBackend


@dataclass(frozen=True, slots=True)
class ConversionPromptVariantEvaluation:
    """Aggregated quality stats for one prompt variant."""

    variant_id: str
    assigned_count: int
    success_count: int
    failed_count: int
    parse_warnings_count: int
    success_rate: float
    warning_rate: float


@dataclass(frozen=True, slots=True)
class ConversionPromptEvaluationSummary:
    """Operation-level prompt A/B evaluation summary."""

    registry_version: str = "disabled"
    experiment_id: str = "conversion.default.v1"
    assignment_unit: str = PromptAssignmentUnit.SOURCE_PATH.value
    total_assigned_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    parse_warnings_count: int = 0
    variants: tuple[ConversionPromptVariantEvaluation, ...] = ()
    best_variant_id: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionPromptRegistry:
    """Versioned prompt registry for deterministic conversion experiments."""

    enabled: bool
    registry_version: str
    experiment_id: str
    assignment_unit: PromptAssignmentUnit
    seed: str
    variants: tuple[ConversionPromptVariant, ...]

    @classmethod
    def disabled(cls) -> IngestionPromptRegistry:
        """Return deterministic single-variant registry."""
        return cls(
            enabled=False,
            registry_version="disabled",
            experiment_id="conversion.default.v1",
            assignment_unit=PromptAssignmentUnit.SOURCE_PATH,
            seed="adcs-default",
            variants=(
                ConversionPromptVariant(
                    variant_id="deterministic_v1",
                    weight_pct=100,
                    prompt_pack_version="v1",
                    system_prompt_path="prompts/hugo_conversion/system.v1.txt",
                    user_base_prompt_path="prompts/hugo_conversion/user.base.v1.txt",
                    user_docs_prompt_path="prompts/hugo_conversion/user.docs.v1.txt",
                    user_apiref_prompt_path="prompts/hugo_conversion/user.apiref.v1.txt",
                    backend_override=IngestionLLMBackend.DETERMINISTIC,
                ),
            ),
        )

    @classmethod
    def from_config_file(
        cls,
        *,
        config_path: str | Path,
    ) -> IngestionPromptRegistry:
        """Load prompt registry from JSON file, fallback to deterministic default."""
        resolved_path = Path(config_path)
        if not resolved_path.exists():
            return cls.disabled()

        parsed = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            msg = "ingestion_prompt_registry config must be a JSON object."
            raise ValueError(msg)

        defaults = cls.disabled()
        enabled = bool(parsed.get("enabled", defaults.enabled))
        registry_version = _read_non_empty_string(
            parsed.get("registry_version"),
            field_name="registry_version",
            default_value=defaults.registry_version,
        )
        conversion_experiment = parsed.get("conversion_experiment", {})
        if not isinstance(conversion_experiment, dict):
            msg = "`conversion_experiment` must be a JSON object."
            raise ValueError(msg)

        experiment_id = _read_non_empty_string(
            conversion_experiment.get("experiment_id"),
            field_name="conversion_experiment.experiment_id",
            default_value=defaults.experiment_id,
        )
        assignment_unit = _parse_assignment_unit(
            conversion_experiment.get("assignment_unit", defaults.assignment_unit.value)
        )
        seed = _read_non_empty_string(
            conversion_experiment.get("seed"),
            field_name="conversion_experiment.seed",
            default_value=defaults.seed,
        )
        variants = _parse_variants(
            conversion_experiment.get("variants"),
            defaults=defaults.variants,
        )
        return cls(
            enabled=enabled,
            registry_version=registry_version,
            experiment_id=experiment_id,
            assignment_unit=assignment_unit,
            seed=seed,
            variants=variants,
        )

    def assign(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_path: str,
        fallback_backend: IngestionLLMBackend,
    ) -> ConversionPromptAssignment:
        """Resolve one deterministic assignment for a conversion input file."""
        variant = self._pick_variant(
            repo_id=repo_id,
            source_kind=source_kind,
            source_path=source_path,
        )
        user_prompt_path = _resolve_user_prompt_path(
            variant=variant,
            source_kind=source_kind,
        )
        return ConversionPromptAssignment(
            repo_id=repo_id,
            source_kind=source_kind,
            source_path=source_path,
            variant_id=variant.variant_id,
            prompt_pack_version=variant.prompt_pack_version,
            system_prompt_path=variant.system_prompt_path,
            user_prompt_path=user_prompt_path,
            backend=variant.backend_override or fallback_backend,
        )

    def evaluate(
        self,
        *,
        assignments: tuple[ConversionPromptAssignment, ...],
        failed_source_paths: tuple[str, ...],
        parse_warnings_by_source_path: dict[str, int],
    ) -> ConversionPromptEvaluationSummary:
        """Build operation-level A/B evaluation summary from conversion output."""
        if not assignments:
            return ConversionPromptEvaluationSummary(
                registry_version=self.registry_version,
                experiment_id=self.experiment_id,
                assignment_unit=self.assignment_unit.value,
            )

        failed = set(failed_source_paths)
        per_variant: dict[str, dict[str, int]] = {}
        total_warnings = 0

        for assignment in assignments:
            stats = per_variant.setdefault(
                assignment.variant_id,
                {
                    "assigned_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "parse_warnings_count": 0,
                },
            )
            stats["assigned_count"] += 1
            warnings_count = max(
                0,
                int(parse_warnings_by_source_path.get(assignment.source_path, 0)),
            )
            stats["parse_warnings_count"] += warnings_count
            total_warnings += warnings_count
            if assignment.source_path in failed:
                stats["failed_count"] += 1
            else:
                stats["success_count"] += 1

        variants: list[ConversionPromptVariantEvaluation] = []
        for variant_id, stats in sorted(per_variant.items()):
            assigned_count = stats["assigned_count"]
            success_count = stats["success_count"]
            warnings_count = stats["parse_warnings_count"]
            success_rate = (
                success_count / float(assigned_count) if assigned_count > 0 else 0.0
            )
            warning_rate = (
                warnings_count / float(assigned_count) if assigned_count > 0 else 0.0
            )
            variants.append(
                ConversionPromptVariantEvaluation(
                    variant_id=variant_id,
                    assigned_count=assigned_count,
                    success_count=success_count,
                    failed_count=stats["failed_count"],
                    parse_warnings_count=warnings_count,
                    success_rate=round(success_rate, 4),
                    warning_rate=round(warning_rate, 4),
                )
            )

        best_variant_id = _resolve_best_variant_id(tuple(variants))
        return ConversionPromptEvaluationSummary(
            registry_version=self.registry_version,
            experiment_id=self.experiment_id,
            assignment_unit=self.assignment_unit.value,
            total_assigned_count=len(assignments),
            successful_count=len(assignments) - len(failed),
            failed_count=len(failed),
            parse_warnings_count=total_warnings,
            variants=tuple(variants),
            best_variant_id=best_variant_id,
        )

    def safe_summary(self) -> dict[str, object]:
        """Return redacted registry summary for logs/telemetry."""
        return {
            "enabled": self.enabled,
            "registry_version": self.registry_version,
            "experiment_id": self.experiment_id,
            "assignment_unit": self.assignment_unit.value,
            "variants": [
                {
                    "variant_id": variant.variant_id,
                    "weight_pct": variant.weight_pct,
                    "prompt_pack_version": variant.prompt_pack_version,
                    "backend_override": (
                        variant.backend_override.value
                        if variant.backend_override is not None
                        else None
                    ),
                }
                for variant in self.variants
            ],
        }

    def _pick_variant(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_path: str,
    ) -> ConversionPromptVariant:
        if not self.enabled or len(self.variants) == 1:
            return self.variants[0]

        if self.assignment_unit is PromptAssignmentUnit.SOURCE_PATH:
            assignment_key = (
                f"{self.seed}|{self.experiment_id}|{repo_id}|{source_kind}|{source_path}"
            )
        else:
            assignment_key = f"{self.seed}|{self.experiment_id}|{repo_id}|{source_path}"

        digest = hashlib.sha256(assignment_key.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        cumulative = 0
        selected = self.variants[-1]
        for variant in self.variants:
            cumulative += variant.weight_pct
            if bucket < cumulative:
                selected = variant
                break
        return selected


def _read_non_empty_string(
    raw_value: object,
    *,
    field_name: str,
    default_value: str,
) -> str:
    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str):
        msg = f"`{field_name}` must be a string."
        raise ValueError(msg)
    normalized = raw_value.strip()
    if not normalized:
        msg = f"`{field_name}` must not be empty."
        raise ValueError(msg)
    return normalized


def _parse_assignment_unit(raw_value: object) -> PromptAssignmentUnit:
    if not isinstance(raw_value, str):
        msg = "`conversion_experiment.assignment_unit` must be a string."
        raise ValueError(msg)
    normalized = raw_value.strip().lower()
    try:
        return PromptAssignmentUnit(normalized)
    except ValueError as exc:
        msg = f"Unsupported assignment_unit: `{raw_value}`."
        raise ValueError(msg) from exc


def _parse_variants(
    raw_value: object,
    *,
    defaults: tuple[ConversionPromptVariant, ...],
) -> tuple[ConversionPromptVariant, ...]:
    if raw_value is None:
        return defaults
    if not isinstance(raw_value, list) or not raw_value:
        msg = "`conversion_experiment.variants` must be a non-empty array."
        raise ValueError(msg)

    variants: list[ConversionPromptVariant] = []
    seen_variant_ids: set[str] = set()
    for index, item in enumerate(raw_value, start=1):
        if not isinstance(item, dict):
            msg = f"Variant at index {index} must be an object."
            raise ValueError(msg)
        variant_id = _read_non_empty_string(
            item.get("variant_id"),
            field_name=f"variants[{index}].variant_id",
            default_value="",
        )
        if variant_id in seen_variant_ids:
            msg = f"Duplicate prompt variant_id: `{variant_id}`."
            raise ValueError(msg)
        seen_variant_ids.add(variant_id)
        weight_pct = item.get("weight_pct", 0)
        if not isinstance(weight_pct, int) or weight_pct < 1 or weight_pct > 100:
            msg = f"`variants[{index}].weight_pct` must be an integer in [1, 100]."
            raise ValueError(msg)

        backend_override_raw = item.get("backend_override")
        backend_override: IngestionLLMBackend | None
        if backend_override_raw is None:
            backend_override = None
        elif isinstance(backend_override_raw, str):
            normalized_backend = backend_override_raw.strip().lower()
            try:
                backend_override = IngestionLLMBackend(normalized_backend)
            except ValueError as exc:
                msg = (
                    f"`variants[{index}].backend_override` has unsupported value "
                    f"`{backend_override_raw}`."
                )
                raise ValueError(msg) from exc
        else:
            msg = f"`variants[{index}].backend_override` must be a string when provided."
            raise ValueError(msg)

        variants.append(
            ConversionPromptVariant(
                variant_id=variant_id,
                weight_pct=weight_pct,
                prompt_pack_version=_read_non_empty_string(
                    item.get("prompt_pack_version"),
                    field_name=f"variants[{index}].prompt_pack_version",
                    default_value="v1",
                ),
                system_prompt_path=_read_non_empty_string(
                    item.get("system_prompt_path"),
                    field_name=f"variants[{index}].system_prompt_path",
                    default_value="prompts/hugo_conversion/system.v1.txt",
                ),
                user_base_prompt_path=_read_non_empty_string(
                    item.get("user_base_prompt_path"),
                    field_name=f"variants[{index}].user_base_prompt_path",
                    default_value="prompts/hugo_conversion/user.base.v1.txt",
                ),
                user_docs_prompt_path=_read_non_empty_string(
                    item.get("user_docs_prompt_path"),
                    field_name=f"variants[{index}].user_docs_prompt_path",
                    default_value="prompts/hugo_conversion/user.docs.v1.txt",
                ),
                user_apiref_prompt_path=_read_non_empty_string(
                    item.get("user_apiref_prompt_path"),
                    field_name=f"variants[{index}].user_apiref_prompt_path",
                    default_value="prompts/hugo_conversion/user.apiref.v1.txt",
                ),
                backend_override=backend_override,
            )
        )

    total_weight = sum(variant.weight_pct for variant in variants)
    if total_weight != 100:
        msg = "`conversion_experiment.variants` weight_pct sum must equal 100."
        raise ValueError(msg)
    return tuple(variants)


def _resolve_user_prompt_path(
    *,
    variant: ConversionPromptVariant,
    source_kind: str,
) -> str:
    normalized = source_kind.strip().casefold()
    if normalized == "apiref":
        return variant.user_apiref_prompt_path
    if normalized == "docs":
        return variant.user_docs_prompt_path
    return variant.user_base_prompt_path


def _resolve_best_variant_id(
    variants: tuple[ConversionPromptVariantEvaluation, ...],
) -> str | None:
    if not variants:
        return None
    ranked = sorted(
        variants,
        key=lambda item: (
            item.success_rate,
            -item.warning_rate,
            item.success_count,
            item.assigned_count,
            item.variant_id,
        ),
        reverse=True,
    )
    return ranked[0].variant_id
