"""Engine-owned, exact provider contract registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts.port import canonical_fingerprint

PROVIDER_MANIFEST_NAME = "provider_contracts-1.1.0.json"
PROVIDER_MANIFEST_SCHEMA = "se-provider-contracts/1.1.0"
PROVIDER_MANIFEST_REVISION = "provider.contracts.2"
_ABILITY_PROVIDER_EXPECTED = {
    "provider_ref": "provider.ability.execution.1",
    "capability_id": "ability.execution", "capability_version": "1.0.0",
    "profile_id": "crisis_event", "profile_version": "1.0.0",
    "author_contract": "se-ability-execution-definitions/1.0.0",
    "runtime_contract": "se-ability-execution-runtime/1.0.0",
    "embedded_entrypoint": "story_engine.entrypoints:create_embedded_ability_execution_engine",
    "remote_entrypoint": "story_engine.entrypoints:create_remote_ability_execution_engine",
    "remote_dispatch_contract": "se-remote-dispatch/1.11.0",
    "proposal_only": True, "authority_owner": "321_platform", "legacy": False,
    "real_consumer_source": "events/openings/05_opening_hearing.json",
}


def _material(value: dict[str, Any], excluded: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != excluded}


def load_provider_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or Path(__file__).with_name(PROVIDER_MANIFEST_NAME)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if value.get("schema") != PROVIDER_MANIFEST_SCHEMA or value.get("revision") != PROVIDER_MANIFEST_REVISION:
        raise RuntimeError("provider_contracts.identity_mismatch")
    if value.get("manifest_fingerprint") != canonical_fingerprint(_material(value, "manifest_fingerprint")):
        raise RuntimeError("provider_contracts.fingerprint_mismatch")
    providers = value.get("providers")
    if not isinstance(providers, list):
        raise RuntimeError("provider_contracts.providers_invalid")
    identities: set[tuple[str, str]] = set()
    refs: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise RuntimeError("provider_contracts.provider_invalid")
        identity = (str(provider.get("capability_id")), str(provider.get("capability_version")))
        provider_ref = str(provider.get("provider_ref"))
        if identity in identities or provider_ref in refs:
            raise RuntimeError("provider_contracts.provider_duplicate")
        identities.add(identity); refs.add(provider_ref)
        if provider.get("provider_contract_sha256") != canonical_fingerprint(_material(provider, "provider_contract_sha256")):
            raise RuntimeError("provider_contracts.provider_fingerprint_mismatch")
    ability = [item for item in providers if item.get("capability_id") == "ability.execution" and item.get("capability_version") == "1.0.0"]
    if len(ability) != 1 or any(ability[0].get(key) != item for key, item in _ABILITY_PROVIDER_EXPECTED.items()):
        raise RuntimeError("provider_contracts.ability_contract_mismatch")
    return value


def resolve_provider(capability_id: str, capability_version: str, path: Path | None = None) -> dict[str, Any]:
    matches = [item for item in load_provider_manifest(path)["providers"] if item["capability_id"] == capability_id and item["capability_version"] == capability_version]
    if len(matches) != 1:
        raise LookupError(f"provider_contracts.provider_not_exact:{capability_id}/{capability_version}")
    return dict(matches[0])


def provider_manifest_file_sha256(path: Path | None = None) -> str:
    manifest_path = path or Path(__file__).with_name(PROVIDER_MANIFEST_NAME)
    return "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()


__all__ = ["PROVIDER_MANIFEST_NAME", "PROVIDER_MANIFEST_REVISION", "PROVIDER_MANIFEST_SCHEMA", "load_provider_manifest", "provider_manifest_file_sha256", "resolve_provider"]
