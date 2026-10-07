"""Deterministic construction of append-only fixed-candidate release contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


DEV6_VERSION = "1.0.0.dev6"
DEV6_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.8.0"
DEV6_RELEASE_IDENTITY = {
    "scope": "fixed_candidate",
    "id": "party321.story_engine",
    "profile_registry_revision": "se1-p0-conflict-recovery-union/2",
    "distribution_version": DEV6_VERSION,
    "installable": True,
}
DEV7_VERSION = "1.0.0.dev7"
DEV7_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.9.0"
DEV7_RELEASE_IDENTITY = {
    "scope": "fixed_candidate",
    "id": "party321.story_engine",
    "profile_registry_revision": "se1-p0-conflict-recovery-union/2",
    "distribution_version": DEV7_VERSION,
    "installable": True,
}
DEV7_COMPILER_EXTENSION_INVENTORY = {
    "target_abi": "se-compiler/1.9.0",
    "modules": [
        "materials.py",
        "narrative_style.py",
        "story_evolution.py",
        "story_flow.py",
        "v02_extension_candidate.py",
    ],
    "schemas": [
        "se-canonical-story-pack-ir-1.9.0.schema.json",
        "se-material-coverage-1.0.0.schema.json",
        "se-material-documentation-manifest-1.0.0.schema.json",
        "se-material-ir-1.0.0.schema.json",
        "se-material-slice-1.0.0.schema.json",
        "se-narrative-style-candidate-runtime-1.0.0.schema.json",
        "se-narrative-style-ir-1.0.0.schema.json",
        "se-narrative-style-profile-1.0.0.schema.json",
        "se-story-artifact-1.9.0.schema.json",
        "se-story-evolution-context-1.0.0.schema.json",
        "se-story-evolution-definition-1.0.0.schema.json",
        "se-story-evolution-ir-1.0.0.schema.json",
        "se-story-evolution-proposal-batch-1.0.0.schema.json",
        "se-story-flow-ir-1.0.0.schema.json",
        "se-story-flow-recipe-1.0.0.schema.json",
    ],
    "conformance": [
        "material-vectors-1.0.0.json",
        "narrative-style-vectors-1.0.0.json",
        "story-evolution-vectors-1.0.0.json",
        "story-flow-vectors-1.0.0.json",
    ],
}
POST_RESOLUTION_ENTRYPOINTS = {
    "party321.story_engine.embedded": "story_engine.entrypoints:create_embedded_post_resolution_engine",
    "party321.story_engine.remote": "story_engine.entrypoints:create_remote_post_resolution_engine",
}
POST_RESOLUTION_EXTENSION = {
    "extension_contract": "se-post-resolution-generation-request/1.0.0",
    "capability": "post_resolution.narrative/1.0.0",
    "embedded_entrypoint": "post_resolution",
    "remote_entrypoint": "post_resolution",
    "remote_dispatch_contract": "se-post-resolution-remote-dispatch/1.0.0",
    "operation": "generate_post_resolution",
    "authority_owner": "321_platform",
    "engine_role": "proposal_only",
    "commits_state": False,
    "unknown_required_policy": "fail_closed",
}
POST_RESOLUTION_FACTORY_ARGUMENTS = {
    "artifact": "required",
    "artifact_ref": "required",
    "provider_capabilities": "required",
}
STORY_EVOLUTION_ENTRYPOINTS = {
    "party321.story_engine.embedded": "story_engine.entrypoints:create_embedded_story_evolution_engine",
    "party321.story_engine.remote": "story_engine.entrypoints:create_remote_story_evolution_engine",
}
STORY_EVOLUTION_EXTENSION = {
    "extension_contract": "se-story-evolution-context/1.0.0",
    "capability": "story.evolution.bounded/1",
    "embedded_entrypoint": "story_evolution",
    "remote_entrypoint": "story_evolution",
    "remote_dispatch_contract": "se-story-evolution-remote-dispatch/1.0.0",
    "operation": "generate_story_evolution",
    "authority_owner": "321_platform",
    "engine_role": "proposal_only",
    "commits_state": False,
    "unknown_required_policy": "fail_closed",
}
STORY_EVOLUTION_FACTORY_ARGUMENTS = {
    "artifact": "required",
    "artifact_ref": "required",
    "provider_capabilities": "required",
}

TERMINAL_RISK_VERSION = "1.0.0.dev7+rc.1"
TERMINAL_RISK_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.10.0"
TERMINAL_RISK_RELEASE_IDENTITY = {**DEV7_RELEASE_IDENTITY, "distribution_version":TERMINAL_RISK_VERSION}
TERMINAL_RISK_EXTENSION = {
    "extension_contract":"se-terminal-risk-evaluation/1.0.0", "capability":"story_flow.terminal_risk/1.0.0",
    "embedded_entrypoint":"terminal_risk", "remote_entrypoint":"terminal_risk",
    "remote_dispatch_contract":"se-terminal-risk-remote-dispatch/1.0.0", "operation":"evaluate_terminal_risk",
    "authority_owner":"321_platform", "engine_role":"proposal_only", "commits_state":False,
    "unknown_required_policy":"fail_closed",
}
TERMINAL_RISK_FACTORY_ARGUMENTS = {"artifact":"required", "artifact_ref":"required"}
TERMINAL_RISK_COMPILER_INVENTORY = deepcopy(DEV7_COMPILER_EXTENSION_INVENTORY)
TERMINAL_RISK_COMPILER_INVENTORY['target_abi']='se-compiler/1.10.0'
TERMINAL_RISK_COMPILER_INVENTORY['modules']=sorted(TERMINAL_RISK_COMPILER_INVENTORY['modules']+['terminal_risk.py'])
TERMINAL_RISK_COMPILER_INVENTORY['schemas']=sorted([
    name.replace('story-pack-ir-1.9.0','story-pack-ir-1.10.0').replace('story-artifact-1.9.0','story-artifact-1.10.0')
    for name in TERMINAL_RISK_COMPILER_INVENTORY['schemas']
]+['se-terminal-risk-ir-1.0.0.schema.json'])


def build_dev6_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str, Any]:
    """Return the append-only dev6 contract without mutating the fixed dev5 source."""

    value = deepcopy(dict(base))
    if value.get("schema") != "se-story-engine-entrypoints/1.7.0":
        raise ValueError("dev6 entrypoint base must be the fixed 1.7.0 dev5 contract")
    value["schema"] = DEV6_ENTRYPOINT_SCHEMA
    value["status"] = "fixed_candidate_built_not_promoted" if built else "fixed_candidate_source_authorized_not_built"
    value["engine_version"] = DEV6_VERSION
    compatibility = value.get("compatibility")
    if not isinstance(compatibility, dict):
        raise ValueError("entrypoint compatibility is missing")
    compatibility["preserved_entrypoints_contract"] = "se-story-engine-entrypoints/1.7.0"
    inventory = value.get("entrypoint_inventory")
    if not isinstance(inventory, dict):
        raise ValueError("entrypoint inventory is missing")
    for group, target in POST_RESOLUTION_ENTRYPOINTS.items():
        group_value = inventory.get(group)
        if not isinstance(group_value, dict):
            raise ValueError(f"entrypoint group is missing: {group}")
        group_value["post_resolution"] = target
        inventory[group] = {key: group_value[key] for key in sorted(group_value)}
    extensions = value.get("extensions")
    if not isinstance(extensions, dict):
        raise ValueError("entrypoint extensions are missing")
    extensions["post_resolution"] = deepcopy(POST_RESOLUTION_EXTENSION)
    value["extensions"] = {key: extensions[key] for key in sorted(extensions)}
    manifest_shape = value.get("manifest_shape")
    if not isinstance(manifest_shape, dict):
        raise ValueError("entrypoint manifest shape is missing")
    manifest_shape["entrypoints_schema"] = DEV6_ENTRYPOINT_SCHEMA
    manifest_shape["optional_extensions"] = sorted(extensions)
    rules = value.get("factory_argument_rules")
    if not isinstance(rules, dict):
        raise ValueError("entrypoint factory rules are missing")
    for field in ("extension_parameters", "entrypoint_parameters"):
        parameters = rules.get(field)
        if not isinstance(parameters, dict):
            raise ValueError(f"entrypoint factory rules missing {field}")
        parameters["post_resolution"] = deepcopy(POST_RESOLUTION_FACTORY_ARGUMENTS)
        rules[field] = {key: parameters[key] for key in sorted(parameters)}
    dependencies = value.get("operation_dependencies")
    if not isinstance(dependencies, dict):
        raise ValueError("entrypoint operation dependencies are missing")
    dependencies["generate_post_resolution"] = [
        "story_artifact",
        "platform_bridge",
        "provider:structured_output",
        "platform committed mechanical receipt and authoritative bindings",
    ]
    optional = value.get("optional_engine_capabilities")
    if not isinstance(optional, list):
        raise ValueError("optional engine capabilities are missing")
    value["optional_engine_capabilities"] = sorted(set(optional) | {"post_resolution.narrative/1.0.0"})
    value["release_index_built"] = built
    value["bundle_built"] = built
    value["wheel_built"] = built
    value["release_identity"] = deepcopy(DEV6_RELEASE_IDENTITY)
    value["installable"] = True
    return value


def build_dev7_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str, Any]:
    """Promote the dev6 shape append-only while preserving its 14-per-group runtime API."""

    value = build_dev6_entrypoint_contract(base, built=built)
    value["schema"] = DEV7_ENTRYPOINT_SCHEMA
    value["status"] = "fixed_candidate_built_not_promoted" if built else "fixed_candidate_source_authorized_not_built"
    value["engine_version"] = DEV7_VERSION
    value["compatibility"]["preserved_entrypoints_contract"] = DEV6_ENTRYPOINT_SCHEMA
    value["manifest_shape"]["entrypoints_schema"] = DEV7_ENTRYPOINT_SCHEMA
    inventory = value["entrypoint_inventory"]
    for group, target in STORY_EVOLUTION_ENTRYPOINTS.items():
        group_value = inventory[group]
        group_value["story_evolution"] = target
        inventory[group] = {key: group_value[key] for key in sorted(group_value)}
    extensions = value["extensions"]
    extensions["story_evolution"] = deepcopy(STORY_EVOLUTION_EXTENSION)
    value["extensions"] = {key: extensions[key] for key in sorted(extensions)}
    value["manifest_shape"]["optional_extensions"] = sorted(value["extensions"])
    for field in ("extension_parameters", "entrypoint_parameters"):
        parameters = value["factory_argument_rules"][field]
        parameters["story_evolution"] = deepcopy(STORY_EVOLUTION_FACTORY_ARGUMENTS)
        value["factory_argument_rules"][field] = {key: parameters[key] for key in sorted(parameters)}
    value["operation_dependencies"]["generate_story_evolution"] = [
        "story_artifact", "platform_bridge", "provider:structured_output",
        "platform authoritative StoryEvolution context and installed IR pin",
    ]
    value["optional_engine_capabilities"] = sorted(
        set(value["optional_engine_capabilities"]) | {"story.evolution.bounded/1"}
    )
    value["compiler_extension_inventory"] = deepcopy(DEV7_COMPILER_EXTENSION_INVENTORY)
    value["release_identity"] = deepcopy(DEV7_RELEASE_IDENTITY)
    return value


def build_terminal_risk_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str,Any]:
    value=build_dev7_entrypoint_contract(base,built=built)
    value['schema']=TERMINAL_RISK_ENTRYPOINT_SCHEMA
    value['engine_version']=TERMINAL_RISK_VERSION
    value['compatibility']['preserved_entrypoints_contract']=DEV7_ENTRYPOINT_SCHEMA
    value['manifest_shape']['entrypoints_schema']=TERMINAL_RISK_ENTRYPOINT_SCHEMA
    for group,kind in [('party321.story_engine.embedded','embedded'),('party321.story_engine.remote','remote')]:
        inventory=value['entrypoint_inventory'][group]
        inventory['terminal_risk']=f'story_engine.terminal_risk:create_{kind}_terminal_risk_engine'
        value['entrypoint_inventory'][group]=dict(sorted(inventory.items()))
    value['extensions']['terminal_risk']=deepcopy(TERMINAL_RISK_EXTENSION)
    value['extensions']=dict(sorted(value['extensions'].items()))
    value['manifest_shape']['optional_extensions']=sorted(value['extensions'])
    for field in ['extension_parameters','entrypoint_parameters']:
        value['factory_argument_rules'][field]['terminal_risk']=deepcopy(TERMINAL_RISK_FACTORY_ARGUMENTS)
        value['factory_argument_rules'][field]=dict(sorted(value['factory_argument_rules'][field].items()))
    value['operation_dependencies']['evaluate_terminal_risk']=['story_artifact','platform committed terminal-condition receipts']
    value['optional_engine_capabilities']=sorted(set(value['optional_engine_capabilities'])|{'story_flow.terminal_risk/1.0.0'})
    value['compiler_extension_inventory']=deepcopy(TERMINAL_RISK_COMPILER_INVENTORY)
    value['release_identity']=deepcopy(TERMINAL_RISK_RELEASE_IDENTITY)
    return value


BRIEF_START_VERSION = "1.0.0.dev7+rc.2"
BRIEF_START_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.11.0"
BRIEF_START_RELEASE_IDENTITY = {**TERMINAL_RISK_RELEASE_IDENTITY, "distribution_version": BRIEF_START_VERSION}
BRIEF_START_EXTENSION = {
    "extension_contract": "se-brief-start/1.0.0", "capability": "story.brief_start/1.0.0",
    "embedded_entrypoint": "brief_start", "remote_entrypoint": "brief_start",
    "remote_dispatch_contract": "se-brief-start/1.0.0", "operation": "generate_initial_story",
    "authority_owner": "321_platform", "engine_role": "proposal_only", "commits_state": False,
    "unknown_required_policy": "fail_closed",
}
BRIEF_START_FACTORY_ARGUMENTS = {"artifact": "optional", "artifact_ref": "optional"}
BRIEF_START_COMPILER_INVENTORY = deepcopy(TERMINAL_RISK_COMPILER_INVENTORY)
BRIEF_START_COMPILER_INVENTORY["modules"] = sorted(BRIEF_START_COMPILER_INVENTORY["modules"] + ["brief_start.py", "default_rules.py"])


def build_brief_start_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str, Any]:
    """Add room-brief hosting without changing the existing Pack compiler ABI."""
    value = build_terminal_risk_entrypoint_contract(base, built=built)
    value["schema"] = BRIEF_START_ENTRYPOINT_SCHEMA
    value["engine_version"] = BRIEF_START_VERSION
    value["compatibility"]["preserved_entrypoints_contract"] = TERMINAL_RISK_ENTRYPOINT_SCHEMA
    value["manifest_shape"]["entrypoints_schema"] = BRIEF_START_ENTRYPOINT_SCHEMA
    for kind in ("embedded", "remote"):
        inventory = value["entrypoint_inventory"][f"party321.story_engine.{kind}"]
        inventory["brief_start"] = f"story_engine.brief_start:create_{kind}_brief_start_engine"
        value["entrypoint_inventory"][f"party321.story_engine.{kind}"] = dict(sorted(inventory.items()))
    value["extensions"]["brief_start"] = deepcopy(BRIEF_START_EXTENSION)
    value["extensions"] = dict(sorted(value["extensions"].items()))
    value["manifest_shape"]["optional_extensions"] = sorted(value["extensions"])
    for field in ("extension_parameters", "entrypoint_parameters"):
        value["factory_argument_rules"][field]["brief_start"] = deepcopy(BRIEF_START_FACTORY_ARGUMENTS)
        value["factory_argument_rules"][field] = dict(sorted(value["factory_argument_rules"][field].items()))
    value["operation_dependencies"]["generate_initial_story"] = ["platform_bridge", "provider:structured_output", "platform authorized room brief and member snapshot"]
    value["optional_engine_capabilities"] = sorted(set(value["optional_engine_capabilities"]) | {"story.brief_start/1.0.0"})
    value["compiler_extension_inventory"] = deepcopy(BRIEF_START_COMPILER_INVENTORY)
    value["release_identity"] = deepcopy(BRIEF_START_RELEASE_IDENTITY)
    return value


from .versions import STORY_ENGINE_DISTRIBUTION_VERSION as HOSTED_TURN_VERSION
HOSTED_TURN_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.12.0"
HOSTED_TURN_RELEASE_IDENTITY = {**BRIEF_START_RELEASE_IDENTITY, "distribution_version": HOSTED_TURN_VERSION}
HOSTED_TURN_EXTENSION = {
    "extension_contract":"se-hosted-turn/1.0.0", "capability":"story.hosted_turn/1.0.0",
    "embedded_entrypoint":"hosted_turn", "remote_entrypoint":"hosted_turn",
    "remote_dispatch_contract":"se-hosted-turn/1.0.0", "operation":"propose_intent",
    "authority_owner":"321_platform", "engine_role":"proposal_only", "commits_state":False,
    "unknown_required_policy":"fail_closed",
}
HOSTED_TURN_FACTORY_ARGUMENTS = {"artifact":"optional", "artifact_ref":"optional"}
HOSTED_TURN_COMPILER_INVENTORY = deepcopy(BRIEF_START_COMPILER_INVENTORY)
HOSTED_TURN_COMPILER_INVENTORY['modules'] = sorted(HOSTED_TURN_COMPILER_INVENTORY['modules'] + ['hosted_turn.py'])
# Files the hosted-turn generation releases and must ship in the wheel, kept
# beside the compiler ABI inventory rather than inside it: the platform pins
# that inventory field-for-field in
# party321.infrastructure.engine_bundle._compiler_profile, so extending it needs
# a paired platform change. These entries carry no such coupling.
HOSTED_TURN_CONTRACT_MODULE_NAMES = ('luck_action_bindings.py', 'luck_preparation.py')
HOSTED_TURN_CONTRACT_SCHEMA_NAMES = (
    '321roll-luck-preparation-snapshot-1.0.0.schema.json',
    '321roll-luck-preparation-snapshot-1.1.0.schema.json',
    'se-luck-all-in-bet-1.0.0.schema.json',
    'se-luck-action-bindings-ir-1.0.0.schema.json',
    'se-luck-action-bindings-ir-1.1.0.schema.json',
    'se-canonical-story-pack-ir-1.11.0.schema.json',
    'se-story-artifact-1.11.0.schema.json',
    'se-luck-candidate-proposal-1.0.0.schema.json',
    'se-luck-preparation-proposal-1.0.0.schema.json',
)
if HOSTED_TURN_VERSION in {'1.0.0rc22','1.0.0rc23','1.0.0rc24','1.0.0rc25','1.0.0rc26'}:
    HOSTED_TURN_CONTRACT_MODULE_NAMES += ('compact_narrative.py',)
    HOSTED_TURN_CONTRACT_SCHEMA_NAMES += ('hosted-narrative-model-output/1.7.0/schema.json',)

if HOSTED_TURN_VERSION in {'1.0.0rc25', '1.0.0rc26'}:
    HOSTED_TURN_CONTRACT_MODULE_NAMES += ('play_hooks.py',)
    HOSTED_TURN_CONTRACT_SCHEMA_NAMES += ('hosted-narrative-model-output/1.8.0/schema.json',)


def build_hosted_turn_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str, Any]:
    value = build_brief_start_entrypoint_contract(base,built=built)
    value.update(schema=HOSTED_TURN_ENTRYPOINT_SCHEMA,engine_version=HOSTED_TURN_VERSION)
    value['compatibility']['preserved_entrypoints_contract'] = BRIEF_START_ENTRYPOINT_SCHEMA
    value['manifest_shape']['entrypoints_schema'] = HOSTED_TURN_ENTRYPOINT_SCHEMA
    for kind in ('embedded','remote'):
        inventory=value['entrypoint_inventory'][f'party321.story_engine.{kind}']
        inventory['hosted_turn']=f'story_engine.hosted_turn:create_{kind}_hosted_turn_engine'
        value['entrypoint_inventory'][f'party321.story_engine.{kind}']=dict(sorted(inventory.items()))
    value['extensions']['hosted_turn']=deepcopy(HOSTED_TURN_EXTENSION)
    value['extensions']=dict(sorted(value['extensions'].items()))
    value['manifest_shape']['optional_extensions']=sorted(value['extensions'])
    for field in ('extension_parameters','entrypoint_parameters'):
        value['factory_argument_rules'][field]['hosted_turn']=deepcopy(HOSTED_TURN_FACTORY_ARGUMENTS)
        value['factory_argument_rules'][field]=dict(sorted(value['factory_argument_rules'][field].items()))
    value['operation_dependencies']['propose_intent']=['platform_bridge','provider:structured_output','platform authorized action and committed facts']
    value['operation_dependencies']['narrate_committed']=['platform_bridge','provider:structured_output','platform committed mechanical receipt']
    value['optional_engine_capabilities']=sorted(set(value['optional_engine_capabilities'])|{'story.hosted_turn/1.0.0','story.hosted_resource_actions/1.0.0'})
    value['compiler_extension_inventory']=deepcopy(HOSTED_TURN_COMPILER_INVENTORY)
    value['release_identity']=deepcopy(HOSTED_TURN_RELEASE_IDENTITY)
    return value


# The luck-preparation slice ships its own compiler inventory, so it advances the
# entrypoints schema instead of mutating the hosted-turn 1.12.0 shape an rc12
# package already installs. 1.12.0 keeps its exact old shape and stays fully
# readable; 1.13.0 appends the two modules and four schemas of the luck contract.
LUCK_PREPARATION_ENTRYPOINT_SCHEMA = "se-story-engine-entrypoints/1.13.0"
LUCK_PREPARATION_VERSION = HOSTED_TURN_VERSION
LUCK_PREPARATION_RELEASE_IDENTITY = deepcopy(HOSTED_TURN_RELEASE_IDENTITY)
LUCK_PREPARATION_FACTORY_ARGUMENTS = deepcopy(HOSTED_TURN_FACTORY_ARGUMENTS)
LUCK_PREPARATION_COMPILER_INVENTORY = deepcopy(HOSTED_TURN_COMPILER_INVENTORY)
LUCK_PREPARATION_COMPILER_INVENTORY['modules'] = sorted(
    LUCK_PREPARATION_COMPILER_INVENTORY['modules'] + list(HOSTED_TURN_CONTRACT_MODULE_NAMES))
if LUCK_PREPARATION_VERSION in {'1.0.0rc16', '1.0.0rc19', '1.0.0rc25', '1.0.0rc26'}:
    LUCK_PREPARATION_COMPILER_INVENTORY['modules'] = sorted(
        LUCK_PREPARATION_COMPILER_INVENTORY['modules'] + ['world_rules.py'])
if LUCK_PREPARATION_VERSION in {'1.0.0rc19', '1.0.0rc25', '1.0.0rc26'}:
    LUCK_PREPARATION_COMPILER_INVENTORY['modules'] = sorted(
        LUCK_PREPARATION_COMPILER_INVENTORY['modules'] + ['chapter_plan.py', 'opening_world.py'])
LUCK_PREPARATION_COMPILER_INVENTORY['schemas'] = sorted(
    LUCK_PREPARATION_COMPILER_INVENTORY['schemas'] + list(HOSTED_TURN_CONTRACT_SCHEMA_NAMES))


def build_luck_preparation_entrypoint_contract(base: Mapping[str, Any], *, built: bool = False) -> dict[str, Any]:
    """Append the luck-preparation slice on the unchanged hosted-turn 1.12.0 contract."""
    value = build_hosted_turn_entrypoint_contract(base, built=built)
    value['schema'] = LUCK_PREPARATION_ENTRYPOINT_SCHEMA
    value['engine_version'] = LUCK_PREPARATION_VERSION
    value['compatibility']['preserved_entrypoints_contract'] = HOSTED_TURN_ENTRYPOINT_SCHEMA
    value['manifest_shape']['entrypoints_schema'] = LUCK_PREPARATION_ENTRYPOINT_SCHEMA
    # Luck preparation is a method of the hosted-turn engine, so the extension
    # registry keeps its 1.12.0 identity and only the capability list grows.
    value['optional_engine_capabilities'] = sorted(set(value['optional_engine_capabilities'])|{'luck.preparation/1.0.0'})
    if LUCK_PREPARATION_VERSION in {'1.0.0rc22','1.0.0rc23','1.0.0rc24','1.0.0rc25','1.0.0rc26'}:
        value['optional_engine_capabilities'].append('hosting.compact_narrative/1.0.0')
        value['optional_engine_capabilities'].sort()
    if LUCK_PREPARATION_VERSION in {'1.0.0rc25', '1.0.0rc26'}:
        value['optional_engine_capabilities'] = sorted(set(value['optional_engine_capabilities']) | {'hosting.play_hooks/1.0.0'})
    value['compiler_extension_inventory'] = deepcopy(LUCK_PREPARATION_COMPILER_INVENTORY)
    value['release_identity'] = deepcopy(LUCK_PREPARATION_RELEASE_IDENTITY)
    if LUCK_PREPARATION_VERSION in {'1.0.0rc15', '1.0.0rc16', '1.0.0rc19', '1.0.0rc25', '1.0.0rc26'}:
        for kind in ('embedded','remote'):
            inventory=value['entrypoint_inventory'][f'party321.story_engine.{kind}']
            inventory['turn_interaction']=f'story_engine.entrypoints:create_{kind}_turn_interaction_engine'
            value['entrypoint_inventory'][f'party321.story_engine.{kind}']=dict(sorted(inventory.items()))
        value['extensions']['turn_interaction']={
            'extension_contract':'se-turn-interaction-evaluation/1.0.0','capability':'turn.interaction/1.0.0',
            'embedded_entrypoint':'turn_interaction','remote_entrypoint':'turn_interaction',
            'remote_dispatch_contract':'se-remote-dispatch/1.5.0','operation':'evaluate_turn_interaction',
            'authority_owner':'321_platform','engine_role':'proposal_only','commits_state':False,'unknown_required_policy':'fail_closed'}
        value['extensions']=dict(sorted(value['extensions'].items()))
        value['manifest_shape']['optional_extensions']=sorted(value['extensions'])
        for field in ('extension_parameters','entrypoint_parameters'):
            value['factory_argument_rules'][field]['turn_interaction']={'artifact':'required','artifact_ref':'unsupported'}
            value['factory_argument_rules'][field]=dict(sorted(value['factory_argument_rules'][field].items()))
        value['optional_engine_capabilities']=sorted(set(value['optional_engine_capabilities'])|{'turn.interaction/1.0.0'})
        value['operation_dependencies']['evaluate_turn_interaction'] = [
            'story_artifact', 'platform_bridge', 'turn.interaction/1.0.0',
            'platform committed actor, dialogue and phase facts and receipts',
        ]
    if LUCK_PREPARATION_VERSION in {'1.0.0rc16', '1.0.0rc19', '1.0.0rc25', '1.0.0rc26'}:
        value['optional_engine_capabilities'] = sorted(
            set(value['optional_engine_capabilities']) | {'rules.world_template/1.0.0'})
    if LUCK_PREPARATION_VERSION in {'1.0.0rc19', '1.0.0rc25', '1.0.0rc26'}:
        value['optional_engine_capabilities'] = sorted(set(value['optional_engine_capabilities']) |
            {'story.custom_plays/1.0.0','turn.timeout_ranking/1.0.0','story.chapter_plan/1.0.0','story.opening_world/1.0.0'})
    return value


# What the working tree currently builds, named once so the build tooling and the
# platform guard can be compared field for field.
CURRENT_ENTRYPOINT_SCHEMA = LUCK_PREPARATION_ENTRYPOINT_SCHEMA
CURRENT_ENTRYPOINT_VERSION = LUCK_PREPARATION_VERSION
CURRENT_RELEASE_IDENTITY = LUCK_PREPARATION_RELEASE_IDENTITY
CURRENT_COMPILER_INVENTORY = LUCK_PREPARATION_COMPILER_INVENTORY
CURRENT_CONTRACT_MODULE_NAMES = HOSTED_TURN_CONTRACT_MODULE_NAMES
CURRENT_CONTRACT_SCHEMA_NAMES = HOSTED_TURN_CONTRACT_SCHEMA_NAMES
build_current_entrypoint_contract = build_luck_preparation_entrypoint_contract
