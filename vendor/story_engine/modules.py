"""Trusted, immutable capability descriptor registry for the SE 1 module SPI."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from story_engine.contracts.authoring import parse_semver, version_satisfies
from story_engine.contracts.port import PortContractError, ProblemCode, canonical_fingerprint
from story_engine.versions import MODULE_API_VERSION

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


@dataclass(frozen=True, slots=True)
class CapabilityOperation:
    operation_id: str
    input_schema: str
    output_schema: str
    deterministic: bool
    writes: bool
    idempotency_required: bool
    revision_required: bool
    timeout_ms: int

    def __post_init__(self) -> None:
        if _ID_RE.fullmatch(self.operation_id) is None:
            raise ValueError("module.operation_id_invalid")
        if not self.input_schema.strip() or not self.output_schema.strip():
            raise ValueError("module.operation_schema_missing")
        if self.writes:
            raise ValueError("module.operation_direct_write_forbidden")
        if isinstance(self.timeout_ms, bool) or self.timeout_ms <= 0:
            raise ValueError("module.operation_timeout_invalid")


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    version: str
    provider_id: str
    operations: tuple[CapabilityOperation, ...]
    failure_policy: str
    contract_owner: str
    evaluation_owner: str
    authority_owner: str
    execution_owner: str
    projection_owner: str
    late_result_policy: str
    provider_contract_hash: str
    module_api: str = MODULE_API_VERSION
    optional: bool = True

    def __post_init__(self) -> None:
        if _ID_RE.fullmatch(self.capability_id) is None or not self.provider_id.strip():
            raise ValueError("module.capability_or_provider_invalid")
        parse_semver(self.version, path="capability.version")
        if self.module_api != MODULE_API_VERSION or not self.operations:
            raise ValueError("module.api_or_operations_invalid")
        if self.failure_policy not in {"block_writes", "withdraw_capability"}:
            raise ValueError("module.failure_policy_invalid")
        if len({item.operation_id for item in self.operations}) != len(self.operations):
            raise ValueError("module.operation_duplicate")
        owners = (self.contract_owner, self.evaluation_owner, self.authority_owner, self.execution_owner, self.projection_owner, self.late_result_policy)
        if any(not item.strip() for item in owners):
            raise ValueError("module.owner_missing")
        if self.provider_contract_hash != canonical_fingerprint(self.contract_material()):
            raise ValueError("module.provider_contract_hash_mismatch")

    def contract_material(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "module_api": self.module_api,
            "operations": [
                {
                    "operation_id": item.operation_id,
                    "input_schema": item.input_schema,
                    "output_schema": item.output_schema,
                    "deterministic": item.deterministic,
                    "writes": item.writes,
                    "idempotency_required": item.idempotency_required,
                    "revision_required": item.revision_required,
                    "timeout_ms": item.timeout_ms,
                }
                for item in self.operations
            ],
            "failure_policy": self.failure_policy,
        }


def descriptor_hash(*, capability_id: str, version: str, operations: tuple[CapabilityOperation, ...], failure_policy: str) -> str:
    return canonical_fingerprint({
        "capability_id": capability_id,
        "version": version,
        "module_api": MODULE_API_VERSION,
        "operations": [
            {
                "operation_id": item.operation_id,
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
                "deterministic": item.deterministic,
                "writes": item.writes,
                "idempotency_required": item.idempotency_required,
                "revision_required": item.revision_required,
                "timeout_ms": item.timeout_ms,
            }
            for item in operations
        ],
        "failure_policy": failure_policy,
    })


class CapabilityRegistry:
    def __init__(self, descriptors: Iterable[CapabilityDescriptor], *, revision: str) -> None:
        if not revision.strip():
            raise ValueError("module.registry_revision_missing")
        providers: dict[str, CapabilityDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.capability_id in providers:
                raise ValueError("module.active_provider_conflict")
            providers[descriptor.capability_id] = descriptor
        self.revision = revision
        self._providers = MappingProxyType(dict(sorted(providers.items())))
        self.fingerprint = canonical_fingerprint({"revision": revision, "providers": [item.provider_contract_hash for item in self._providers.values()]})

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def resolve(self, capability_id: str, version_range: str, contract_hash: str) -> CapabilityDescriptor:
        descriptor = self._providers.get(capability_id)
        if descriptor is None:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "capability", "必需能力没有受信 provider。")
        if not version_satisfies(descriptor.version, version_range):
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "capability.version", "能力版本不兼容。")
        if descriptor.provider_contract_hash != contract_hash:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "provider_contract_hash", "能力合同摘要不匹配。")
        return descriptor


__all__ = ["CapabilityDescriptor", "CapabilityOperation", "CapabilityRegistry", "descriptor_hash"]
