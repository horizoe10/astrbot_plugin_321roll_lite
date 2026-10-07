"""Deterministic, non-installable aggregate for the v0.2 extension sources.

It compiles four independent v0.2 source families from a real Story Pack and
also exposes the self-contained, fail-closed validation used by the 1.9
compiler ABI.  Validation against a worktree remains the stronger acceptance
gate for callers that have the original Story Pack bytes available.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .materials import MaterialContractError, compile_story_pack_material_candidate, validate_material_ir
from .narrative_style import compile_story_pack_narrative_style_candidate
from .story_evolution import (
    StoryEvolutionContractError, compile_story_evolution_definition,
    project_story_evolution_author_source, validate_story_evolution_ir,
)
from .story_flow import StoryFlowContractError, compile_sp_story_flow_candidate, validate_story_flow_ir
from .terminal_risk import TerminalRiskContractError, compile_terminal_risk_catalog, validate_terminal_risk_ir


V02_EXTENSION_CANDIDATE_SCHEMA = "se-v02-extension-candidate/1.1.0"
LEGACY_EXTENSION_SCHEMA = "se-v02-extension-candidate/1.0.0"

_SOURCE_MODULES: dict[str, tuple[str, ...]] = {
    "author/se1/event_composition_catalog.json": ("terminal_risk",),
    "author/se1/v02/terminal_risk_catalog.json": ("terminal_risk",),
    "README.md": ("materials",),
    "author/se1/narrative_systems.json": ("materials",),
    "author/se1/baimian_event_definitions.json": ("materials",),
    "author/se1/openings_and_routes.json": ("materials", "narrative_style", "story_evolution", "story_flow"),
    "author/se1/world_bible.json": ("materials",),
    "author/se1/v02/documentation_manifest.json": ("materials",),
    "author/se1/v02/material_catalog.json": ("materials",),
    "author/se1/v02/material_coverage.json": ("materials",),
    "author/se1/v02/narrative_style_coverage.json": ("narrative_style",),
    "author/se1/v02/narrative_style_profiles.json": ("narrative_style",),
    "author/se1/v02/story_evolution_coverage.json": ("story_evolution",),
    "author/se1/v02/story_evolution_definition.json": ("story_evolution",),
    "author/se1/v02/story_flow_recipe.json": ("materials", "story_evolution", "story_flow"),
}
_JSON_SOURCE_PATHS = frozenset(path for path in _SOURCE_MODULES if path.endswith(".json"))
_CANDIDATE_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "story_pack_ref", "source_bindings",
    "source_bindings_sha256", "dependency_digests", "dependency_digests_sha256",
    "semantic_digests", "semantic_digests_sha256", "products", "model_calls", "aggregate_sha256",
})
_DEPENDENCY_DIGEST_FIELDS = frozenset({
    "openings_catalog_raw_sha256", "story_flow_recipe_raw_sha256",
    "narrative_style_openings_semantic_sha256", "material_source_authority_sha256",
    "story_flow_opening_catalog_semantic_sha256", "story_evolution_openings_raw_sha256",
    "story_evolution_flow_raw_sha256",
})
_SEMANTIC_DIGEST_FIELDS = frozenset({
    "terminal_risk_ir_sha256",
    "narrative_style_runtime_sha256", "material_ir_sha256", "material_bundle_sha256",
    "story_flow_projection_set_sha256", "story_evolution_definition_sha256",
    "story_evolution_ir_sha256",
})
_PRODUCT_FIELDS = frozenset({"narrative_style", "materials", "story_flow", "story_evolution", "terminal_risk"})
_MODEL_CALL_FIELDS = frozenset({"narrative_style", "materials", "story_flow", "story_evolution", "terminal_risk", "total"})
_SOURCE_BINDING_FIELDS = frozenset({"path", "raw_sha256", "modules"})
_NARRATIVE_STYLE_FIELDS = frozenset({
    "schema", "source_candidate_schema", "coverage_schema", "openings_schema",
    "candidate_version", "installable", "locale", "default_profile_ref",
    "default_preset_ref", "source_style_sha256", "source_coverage_sha256",
    "source_openings_sha256", "requirement_refs", "paragraph_contract",
    "runtime_generation", "preset_catalog", "profile_irs", "adapter_source_map",
    "opening_bindings", "counts", "model_calls", "runtime_sha256",
})
_NARRATIVE_STYLE_IR_FIELDS = frozenset({
    "schema", "source_schema", "profile_ref", "profile_version", "locale", "source_sha256",
    "source_map", "label", "public_summary", "world_voice_summary", "hard_constraints",
    "forbidden_expressions", "phase_variants", "safety_contract_sha256", "runtime_slice_sha256",
    "additional_model_calls", "audience_ceiling", "default_preset", "allowed_presets",
    "customization", "budgets", "style_slices", "ir_sha256",
})
_MATERIAL_FIELDS = frozenset({
    "schema", "material_ir", "slices", "readme_files", "readme_sha256", "model_calls",
    "installable", "integrated_with_dev6", "documentation_manifest",
    "documentation_coverage", "artifact_paths", "bundle_file_digests",
    "candidate_adapter", "candidate_bundle",
})
_MATERIAL_ADAPTER_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "story_pack_ref", "manifest_sha256",
    "catalog_sha256", "coverage_sha256", "source_authority", "physical_slice_paths",
    "model_calls",
})
_MATERIAL_BUNDLE_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "story_pack_ref", "locale",
    "combined_runtime_payload_allowed", "files", "bundle_sha256",
})
_STORY_FLOW_FIELDS = frozenset({
    "opening_ref", "source_opening_id", "recipe", "reference_catalog", "ir",
    "opening_catalog_sha256", "projection_sha256",
})
_STORY_EVOLUTION_FIELDS = frozenset({"definition", "ir"})


@dataclass(frozen=True, slots=True)
class V02ExtensionCandidateError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise V02ExtensionCandidateError(code, path, reason)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("v02_extension.canonical_json_invalid", "$", str(exc))


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("v02_extension.shape_invalid", path, "value must be an object")
    return value


def _sequence(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("v02_extension.shape_invalid", path, "value must be an array")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        _fail(
            "v02_extension.fields_invalid", path,
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}",
        )


def _digest_value(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        _fail("v02_extension.digest_invalid", path, "digest must be sha256:<64 lowercase hex>")
    try:
        int(value[7:], 16)
    except ValueError:
        _fail("v02_extension.digest_invalid", path, "digest must be sha256:<64 lowercase hex>")
    if value != value.lower():
        _fail("v02_extension.digest_invalid", path, "digest must use lowercase hex")
    return value


def _check_embedded_digest(value: Mapping[str, Any], field: str, path: str) -> None:
    declared = _digest_value(value.get(field), f"{path}.{field}")
    material = {key: item for key, item in value.items() if key != field}
    if declared != _digest(material):
        _fail("v02_extension.digest_mismatch", f"{path}.{field}", "embedded product content drift")


def _resolve_source(root: Path, relative: str) -> Path:
    try:
        resolved = (root / Path(relative)).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        _fail("v02_extension.source_missing", relative, str(exc))
    if not resolved.is_file():
        _fail("v02_extension.source_missing", relative, "source must be a regular file")
    return resolved


def _strict_json(payload: bytes, relative: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail("v02_extension.json_duplicate_key", relative, key)
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except V02ExtensionCandidateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("v02_extension.json_invalid", relative, str(exc))
    if not isinstance(value, Mapping):
        _fail("v02_extension.json_invalid", relative, "top-level JSON must be an object")
    return value


def _require_unassigned(product: Mapping[str, Any], path: str) -> None:
    if product.get("candidate_version") != "unassigned" or product.get("installable") is not False:
        _fail("v02_extension.identity_invalid", path, "extension products must remain unassigned and non-installable")


def compile_v02_extension_candidate(worktree_root: str | Path) -> dict[str, Any]:
    """Compile four v0.2 extension families from one real SP worktree."""
    try:
        root = Path(worktree_root).resolve(strict=True)
    except OSError as exc:
        _fail("v02_extension.root_missing", str(worktree_root), str(exc))
    if not root.is_dir():
        _fail("v02_extension.root_missing", str(root), "worktree root must be a directory")

    payloads: dict[str, bytes] = {}
    documents: dict[str, Mapping[str, Any]] = {}
    source_bindings: list[dict[str, Any]] = []
    for relative in sorted(_SOURCE_MODULES):
        payload = _resolve_source(root, relative).read_bytes()
        payloads[relative] = payload
        if relative in _JSON_SOURCE_PATHS:
            documents[relative] = _strict_json(payload, relative)
        source_bindings.append({"path": relative, "raw_sha256": _raw_digest(payload), "modules": list(_SOURCE_MODULES[relative])})

    openings_path = "author/se1/openings_and_routes.json"
    flow_path = "author/se1/v02/story_flow_recipe.json"
    openings = documents[openings_path]
    flow_source = documents[flow_path]
    narrative_style = compile_story_pack_narrative_style_candidate(
        documents["author/se1/v02/narrative_style_profiles.json"],
        documents["author/se1/v02/narrative_style_coverage.json"],
        openings,
    )
    materials = compile_story_pack_material_candidate(root)
    story_flow = compile_sp_story_flow_candidate(flow_source, openings)
    try:
        terminal_risk = compile_terminal_risk_catalog(
            documents["author/se1/v02/terminal_risk_catalog.json"],
            {item["ref"] for item in documents["author/se1/event_composition_catalog.json"]["v02_full_catalog"]["entries"]},
        )
    except TerminalRiskContractError as exc:
        _fail(exc.code, exc.path, str(exc))
    if {item['recipe_ref'] for item in terminal_risk['flow_bindings']} != {item['recipe']['recipe_ref'] for item in story_flow}:
        _fail('terminal_risk.flow_binding_invalid','flow_bindings','risk catalog must bind every compiled StoryFlow recipe')
    evolution_dependencies = {
        "source_catalog_sha256": _raw_digest(payloads[openings_path]),
        "story_flow_recipe_sha256": _raw_digest(payloads[flow_path]),
    }
    evolution_definition = project_story_evolution_author_source(
        documents["author/se1/v02/story_evolution_definition.json"],
        documents["author/se1/v02/story_evolution_coverage.json"],
        flow_source,
        openings,
        evolution_dependencies,
    )
    story_evolution = {"definition": evolution_definition, "ir": compile_story_evolution_definition(evolution_definition)}

    _require_unassigned(narrative_style, "products.narrative_style")
    _require_unassigned(materials["candidate_adapter"], "products.materials.candidate_adapter")
    _require_unassigned(materials["candidate_bundle"], "products.materials.candidate_bundle")
    _require_unassigned(story_evolution["ir"], "products.story_evolution.ir")
    if any(item["recipe"].get("recipe_version") != "0.2-unassigned" for item in story_flow):
        _fail("v02_extension.identity_invalid", "products.story_flow", "StoryFlow projections must remain unassigned")

    binding_by_path = {item["path"]: item for item in source_bindings}
    material_authority = materials["candidate_adapter"]["source_authority"]
    for item in material_authority:
        binding = binding_by_path.get(item["source_ref"])
        if binding is None or binding["raw_sha256"] != "sha256:" + item["sha256"]:
            _fail("v02_extension.dependency_drift", "products.materials", "material authority differs from bound source bytes")
    dependency_digests = {
        "openings_catalog_raw_sha256": evolution_dependencies["source_catalog_sha256"],
        "story_flow_recipe_raw_sha256": evolution_dependencies["story_flow_recipe_sha256"],
        "narrative_style_openings_semantic_sha256": narrative_style["source_openings_sha256"],
        "material_source_authority_sha256": _digest(material_authority),
        "story_flow_opening_catalog_semantic_sha256": story_flow[0]["opening_catalog_sha256"],
        "story_evolution_openings_raw_sha256": story_evolution["ir"]["openings_catalog_sha256"],
        "story_evolution_flow_raw_sha256": story_evolution["ir"]["story_flow_recipe_sha256"],
    }
    if {item["opening_catalog_sha256"] for item in story_flow} != {dependency_digests["story_flow_opening_catalog_semantic_sha256"]}:
        _fail("v02_extension.dependency_drift", "products.story_flow", "opening catalog digest differs across projections")
    if dependency_digests["narrative_style_openings_semantic_sha256"] != dependency_digests["story_flow_opening_catalog_semantic_sha256"]:
        _fail("v02_extension.dependency_drift", "products.narrative_style", "opening semantics differ between compilers")
    if dependency_digests["story_evolution_openings_raw_sha256"] != dependency_digests["openings_catalog_raw_sha256"]:
        _fail("v02_extension.dependency_drift", "products.story_evolution", "opening source digest is not shared")
    if dependency_digests["story_evolution_flow_raw_sha256"] != dependency_digests["story_flow_recipe_raw_sha256"]:
        _fail("v02_extension.dependency_drift", "products.story_evolution", "StoryFlow source digest is not shared")

    model_calls = {
        "narrative_style": narrative_style["model_calls"], "materials": materials["model_calls"],
        "story_flow": 0, "story_evolution": 0,
        "total": narrative_style["model_calls"] + materials["model_calls"],
    }
    model_calls["terminal_risk"] = 0
    if model_calls != dict.fromkeys(_MODEL_CALL_FIELDS, 0):
        _fail("v02_extension.model_call_invalid", "model_calls", "extension compilation must make zero model calls")

    semantic_digests = {
        "terminal_risk_ir_sha256": terminal_risk["ir_sha256"],
        "narrative_style_runtime_sha256": narrative_style["runtime_sha256"],
        "material_ir_sha256": materials["material_ir"]["material_ir_sha256"],
        "material_bundle_sha256": materials["candidate_bundle"]["bundle_sha256"],
        "story_flow_projection_set_sha256": _digest([
            {"opening_ref": item["opening_ref"], "projection_sha256": item["projection_sha256"]}
            for item in story_flow
        ]),
        "story_evolution_definition_sha256": story_evolution["definition"]["definition_sha256"],
        "story_evolution_ir_sha256": story_evolution["ir"]["ir_sha256"],
    }
    candidate: dict[str, Any] = {
        "schema": V02_EXTENSION_CANDIDATE_SCHEMA,
        "candidate_version": "unassigned",
        "installable": False,
        "story_pack_ref": materials["candidate_adapter"]["story_pack_ref"],
        "source_bindings": source_bindings,
        "source_bindings_sha256": _digest(source_bindings),
        "dependency_digests": dependency_digests,
        "dependency_digests_sha256": _digest(dependency_digests),
        "semantic_digests": semantic_digests,
        "semantic_digests_sha256": _digest(semantic_digests),
        "products": {
            "terminal_risk": terminal_risk,
            "narrative_style": narrative_style,
            "materials": materials,
            "story_flow": story_flow,
            "story_evolution": story_evolution,
        },
        "model_calls": model_calls,
    }
    candidate["aggregate_sha256"] = _digest(candidate)
    return candidate


def normalize_v02_extension_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy one aggregate without consulting the source worktree.

    This is the compiler boundary: every identity and digest needed to prove the
    four-product/source closure is contained in the aggregate itself.  It does
    not replace :func:`validate_v02_extension_candidate`, which additionally
    recompiles the real Story Pack bytes.
    """
    candidate = _mapping(value, "$")
    _fields(candidate, _CANDIDATE_FIELDS, "$")
    if candidate.get("schema") not in {V02_EXTENSION_CANDIDATE_SCHEMA,LEGACY_EXTENSION_SCHEMA}:
        _fail("v02_extension.schema_invalid", "schema", "unsupported aggregate schema")
    legacy=candidate.get('schema')==LEGACY_EXTENSION_SCHEMA
    # The frozen dev7 aggregate predates both the terminal-risk sources and the
    # baimian luck-author source, so its exact source closure stays untouched.
    legacy_excluded={path for path,owners in _SOURCE_MODULES.items() if owners==('terminal_risk',)}
    legacy_excluded.add('author/se1/baimian_event_definitions.json')
    expected_modules={path:owners for path,owners in _SOURCE_MODULES.items() if not legacy or path not in legacy_excluded}
    if candidate.get("candidate_version") != "unassigned" or candidate.get("installable") is not False:
        _fail("v02_extension.identity_invalid", "$", "aggregate must remain unassigned and non-installable")
    story_pack_ref = candidate.get("story_pack_ref")
    if not isinstance(story_pack_ref, str) or not story_pack_ref.strip():
        _fail("v02_extension.identity_invalid", "story_pack_ref", "story pack identity must be non-empty text")

    raw_bindings = _sequence(candidate.get("source_bindings"), "source_bindings")
    if len(raw_bindings) != len(expected_modules):
        _fail("v02_extension.source_closure_invalid", "source_bindings", "source closure is incomplete")
    bindings: list[Mapping[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(raw_bindings):
        path = f"source_bindings[{index}]"
        binding = _mapping(raw, path)
        _fields(binding, _SOURCE_BINDING_FIELDS, path)
        relative = binding.get("path")
        if not isinstance(relative, str) or relative not in expected_modules or relative in seen_paths:
            _fail("v02_extension.source_closure_invalid", f"{path}.path", "source path is unknown or duplicated")
        _digest_value(binding.get("raw_sha256"), f"{path}.raw_sha256")
        modules = binding.get("modules")
        if modules != list(expected_modules[relative]):
            _fail("v02_extension.source_closure_invalid", f"{path}.modules", "source module ownership drift")
        seen_paths.add(relative)
        bindings.append(binding)
    if [item["path"] for item in bindings] != sorted(expected_modules):
        _fail("v02_extension.source_closure_invalid", "source_bindings", "source closure must be canonical and sorted")
    if candidate.get("source_bindings_sha256") != _digest(raw_bindings):
        _fail("v02_extension.digest_mismatch", "source_bindings_sha256", "source closure digest drift")
    binding_by_path = {str(item["path"]): item for item in bindings}

    dependencies = _mapping(candidate.get("dependency_digests"), "dependency_digests")
    _fields(dependencies, _DEPENDENCY_DIGEST_FIELDS, "dependency_digests")
    for key, item in dependencies.items():
        _digest_value(item, f"dependency_digests.{key}")
    if candidate.get("dependency_digests_sha256") != _digest(dependencies):
        _fail("v02_extension.digest_mismatch", "dependency_digests_sha256", "dependency digest closure drift")
    if dependencies["openings_catalog_raw_sha256"] != binding_by_path["author/se1/openings_and_routes.json"]["raw_sha256"]:
        _fail("v02_extension.dependency_drift", "dependency_digests.openings_catalog_raw_sha256", "opening source is outside the closure")
    if dependencies["story_flow_recipe_raw_sha256"] != binding_by_path["author/se1/v02/story_flow_recipe.json"]["raw_sha256"]:
        _fail("v02_extension.dependency_drift", "dependency_digests.story_flow_recipe_raw_sha256", "StoryFlow source is outside the closure")

    products = _mapping(candidate.get("products"), "products")
    _fields(products, _PRODUCT_FIELDS-({'terminal_risk'} if legacy else set()), "products")
    if not legacy:
        try:
            validate_terminal_risk_ir(products['terminal_risk'])
        except TerminalRiskContractError as exc:
            _fail(exc.code, exc.path, str(exc))
        if products['terminal_risk']['story_pack_ref']!=story_pack_ref:
            _fail('terminal_risk.identity_invalid','products.terminal_risk','risk IR pack identity mismatch')
    narrative = _mapping(products.get("narrative_style"), "products.narrative_style")
    _fields(narrative, _NARRATIVE_STYLE_FIELDS, "products.narrative_style")
    if narrative.get("schema") not in {'se-narrative-style-candidate-runtime/1.0.0','se-narrative-style-candidate-runtime/1.1.0','se-narrative-style-candidate-runtime/1.2.0','se-narrative-style-candidate-runtime/1.3.0'}:
        _fail("v02_extension.identity_invalid", "products.narrative_style.schema", "NarrativeStyle schema drift")
    _require_unassigned(narrative, "products.narrative_style")
    if narrative.get("model_calls") != 0 or _mapping(narrative.get("runtime_generation"), "products.narrative_style.runtime_generation").get("additional_model_calls") != 0:
        _fail("v02_extension.model_call_invalid", "products.narrative_style", "NarrativeStyle must add zero model calls")
    _check_embedded_digest(narrative, "runtime_sha256", "products.narrative_style")
    for index, raw in enumerate(_sequence(narrative.get("profile_irs"), "products.narrative_style.profile_irs")):
        profile_ir = _mapping(raw, f"products.narrative_style.profile_irs[{index}]")
        _fields(profile_ir, _NARRATIVE_STYLE_IR_FIELDS, f"products.narrative_style.profile_irs[{index}]")
        _check_embedded_digest(profile_ir, "ir_sha256", f"products.narrative_style.profile_irs[{index}]")

    materials = _mapping(products.get("materials"), "products.materials")
    _fields(materials, _MATERIAL_FIELDS, "products.materials")
    if materials.get("model_calls") != 0:
        _fail("v02_extension.model_call_invalid", "products.materials.model_calls", "Material compilation must add zero model calls")
    material_ir = _mapping(materials.get("material_ir"), "products.materials.material_ir")
    if material_ir.get("schema") != "se-material-ir/1.0.0":
        _fail("v02_extension.identity_invalid", "products.materials.material_ir.schema", "Material schema drift")
    _check_embedded_digest(material_ir, "material_ir_sha256", "products.materials.material_ir")
    try:
        validate_material_ir(material_ir)
    except MaterialContractError as exc:
        _fail(exc.code, f"products.materials.{exc.path}", exc.reason)
    adapter = _mapping(materials.get("candidate_adapter"), "products.materials.candidate_adapter")
    bundle = _mapping(materials.get("candidate_bundle"), "products.materials.candidate_bundle")
    _fields(adapter, _MATERIAL_ADAPTER_FIELDS, "products.materials.candidate_adapter")
    _fields(bundle, _MATERIAL_BUNDLE_FIELDS, "products.materials.candidate_bundle")
    _require_unassigned(adapter, "products.materials.candidate_adapter")
    _require_unassigned(bundle, "products.materials.candidate_bundle")
    if adapter.get("story_pack_ref") != story_pack_ref or bundle.get("story_pack_ref") != story_pack_ref or adapter.get("model_calls") != 0:
        _fail("v02_extension.identity_invalid", "products.materials", "Material story-pack identity or model-call policy drift")
    _check_embedded_digest(bundle, "bundle_sha256", "products.materials.candidate_bundle")
    material_authority = _sequence(adapter.get("source_authority"), "products.materials.candidate_adapter.source_authority")
    for index, raw in enumerate(material_authority):
        item = _mapping(raw, f"products.materials.candidate_adapter.source_authority[{index}]")
        if set(item) != {"source_ref", "sha256"}:
            _fail("v02_extension.fields_invalid", f"products.materials.candidate_adapter.source_authority[{index}]", "source authority fields drift")
        binding = binding_by_path.get(str(item.get("source_ref")))
        if binding is None or binding["raw_sha256"] != "sha256:" + str(item.get("sha256")):
            _fail("v02_extension.dependency_drift", "products.materials.candidate_adapter.source_authority", "Material authority differs from bound source bytes")

    story_flow = _sequence(products.get("story_flow"), "products.story_flow")
    if len(story_flow) != 10:
        _fail("v02_extension.source_closure_invalid", "products.story_flow", "StoryFlow must contain exactly ten opening projections")
    opening_refs: set[str] = set()
    source_ids: set[str] = set()
    for index, raw in enumerate(story_flow):
        path = f"products.story_flow[{index}]"
        projection = _mapping(raw, path)
        _fields(projection, _STORY_FLOW_FIELDS, path)
        if projection.get("opening_ref") in opening_refs or projection.get("source_opening_id") in source_ids:
            _fail("v02_extension.source_closure_invalid", path, "StoryFlow opening identity is duplicated")
        opening_refs.add(str(projection.get("opening_ref")))
        source_ids.add(str(projection.get("source_opening_id")))
        recipe = _mapping(projection.get("recipe"), f"{path}.recipe")
        if recipe.get("schema") != "story-flow-recipe/1.0.0" or recipe.get("recipe_version") != "0.2-unassigned":
            _fail("v02_extension.identity_invalid", f"{path}.recipe", "StoryFlow recipe identity drift")
        projection_material = {
            key: item for key, item in projection.items()
            if key not in {"opening_ref", "source_opening_id", "projection_sha256"}
        }
        if projection.get("projection_sha256") != _digest(projection_material):
            _fail("v02_extension.digest_mismatch", f"{path}.projection_sha256", "StoryFlow projection content drift")
        try:
            validate_story_flow_ir(
                _mapping(projection.get("ir"), f"{path}.ir"),
                _mapping(projection.get("reference_catalog"), f"{path}.reference_catalog"),
                recipe,
            )
        except StoryFlowContractError as exc:
            _fail(exc.code, f"{path}.{exc.path}", exc.reason)
    if [item.get("opening_ref") for item in story_flow] != sorted(opening_refs):
        _fail("v02_extension.source_closure_invalid", "products.story_flow", "StoryFlow projections must be canonical and sorted")
    if {item.get("opening_catalog_sha256") for item in story_flow} != {dependencies["story_flow_opening_catalog_semantic_sha256"]}:
        _fail("v02_extension.dependency_drift", "products.story_flow", "opening catalog digest differs across projections")

    evolution = _mapping(products.get("story_evolution"), "products.story_evolution")
    _fields(evolution, _STORY_EVOLUTION_FIELDS, "products.story_evolution")
    evolution_definition = _mapping(evolution.get("definition"), "products.story_evolution.definition")
    evolution_ir = _mapping(evolution.get("ir"), "products.story_evolution.ir")
    if evolution_definition.get("schema") != "se-story-evolution-definition/1.0.0" or evolution_ir.get("schema") != "se-story-evolution-ir/1.0.0":
        _fail("v02_extension.identity_invalid", "products.story_evolution", "StoryEvolution schema drift")
    _require_unassigned(evolution_definition, "products.story_evolution.definition")
    _require_unassigned(evolution_ir, "products.story_evolution.ir")
    _check_embedded_digest(evolution_definition, "definition_sha256", "products.story_evolution.definition")
    _check_embedded_digest(evolution_ir, "ir_sha256", "products.story_evolution.ir")
    if evolution_ir.get("definition_sha256") != evolution_definition.get("definition_sha256"):
        _fail("v02_extension.dependency_drift", "products.story_evolution.ir.definition_sha256", "StoryEvolution definition link drift")
    if evolution_ir.get("runtime_slice_sha256") != _digest(evolution_ir.get("runtime_slice")):
        _fail("v02_extension.digest_mismatch", "products.story_evolution.ir.runtime_slice_sha256", "StoryEvolution runtime slice drift")
    try:
        validate_story_evolution_ir(evolution_ir, evolution_definition)
    except StoryEvolutionContractError as exc:
        _fail(exc.code, f"products.story_evolution.{exc.path}", exc.reason)
    if evolution_ir.get("openings_catalog_sha256") != dependencies["story_evolution_openings_raw_sha256"] or evolution_ir.get("story_flow_recipe_sha256") != dependencies["story_evolution_flow_raw_sha256"]:
        _fail("v02_extension.dependency_drift", "products.story_evolution.ir", "StoryEvolution source link drift")

    semantic = _mapping(candidate.get("semantic_digests"), "semantic_digests")
    _fields(semantic, _SEMANTIC_DIGEST_FIELDS-({'terminal_risk_ir_sha256'} if legacy else set()), "semantic_digests")
    for key, item in semantic.items():
        _digest_value(item, f"semantic_digests.{key}")
    expected_semantic = {
        "narrative_style_runtime_sha256": narrative["runtime_sha256"],
        "material_ir_sha256": material_ir["material_ir_sha256"],
        "material_bundle_sha256": bundle["bundle_sha256"],
        "story_flow_projection_set_sha256": _digest([
            {"opening_ref": item["opening_ref"], "projection_sha256": item["projection_sha256"]}
            for item in story_flow
        ]),
        "story_evolution_definition_sha256": evolution_definition["definition_sha256"],
        "story_evolution_ir_sha256": evolution_ir["ir_sha256"],
    }
    if not legacy:expected_semantic['terminal_risk_ir_sha256']=products['terminal_risk']['ir_sha256']
    if dict(semantic) != expected_semantic or candidate.get("semantic_digests_sha256") != _digest(semantic):
        _fail("v02_extension.digest_mismatch", "semantic_digests", "semantic product closure drift")
    if dependencies["narrative_style_openings_semantic_sha256"] != narrative.get("source_openings_sha256") or dependencies["narrative_style_openings_semantic_sha256"] != dependencies["story_flow_opening_catalog_semantic_sha256"]:
        _fail("v02_extension.dependency_drift", "dependency_digests", "NarrativeStyle and StoryFlow opening semantics differ")
    if dependencies["material_source_authority_sha256"] != _digest(material_authority):
        _fail("v02_extension.dependency_drift", "dependency_digests.material_source_authority_sha256", "Material source authority digest drift")
    if dependencies["story_evolution_openings_raw_sha256"] != dependencies["openings_catalog_raw_sha256"] or dependencies["story_evolution_flow_raw_sha256"] != dependencies["story_flow_recipe_raw_sha256"]:
        _fail("v02_extension.dependency_drift", "dependency_digests", "StoryEvolution raw source closure drift")

    model_calls = _mapping(candidate.get("model_calls"), "model_calls")
    model_fields = _MODEL_CALL_FIELDS - ({"terminal_risk"} if legacy else set())
    _fields(model_calls, model_fields, "model_calls")
    if dict(model_calls) != dict.fromkeys(model_fields, 0) or any(type(value) is not int for value in model_calls.values()):
        _fail("v02_extension.model_call_invalid", "model_calls", "extension compilation must make zero model calls")
    if candidate.get("aggregate_sha256") != _digest({key: item for key, item in candidate.items() if key != "aggregate_sha256"}):
        _fail("v02_extension.digest_mismatch", "aggregate_sha256", "aggregate content drift")
    return json.loads(_canonical_bytes(candidate).decode("utf-8"))


def validate_v02_extension_candidate(value: Mapping[str, Any], worktree_root: str | Path) -> None:
    """Fail closed unless ``value`` is byte-equivalent to a real recompilation."""
    normalized = normalize_v02_extension_candidate(value)
    if _canonical_bytes(normalized) != _canonical_bytes(compile_v02_extension_candidate(worktree_root)):
        _fail("v02_extension.product_mismatch", "$", "candidate differs from exact real-source recompilation")


def canonical_v02_extension_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the canonical UTF-8 representation used by all aggregate digests."""
    return _canonical_bytes(value)


__all__ = [
    "V02_EXTENSION_CANDIDATE_SCHEMA",
    "V02ExtensionCandidateError",
    "canonical_v02_extension_bytes",
    "compile_v02_extension_candidate",
    "normalize_v02_extension_candidate",
    "validate_v02_extension_candidate",
]
