"""Compile declared risk policy and interpret committed terminal conditions.

The platform supplies randomness, authoritative observations, and receipts.
This module only compiles author data and returns an uncommitted decision.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

AUTHOR_SCHEMA = "sp-terminal-risk-catalog/0.2"
IR_SCHEMA = "se-terminal-risk-ir/1.0.0"
CONDITIONS = frozenset({
    "public_warning_committed", "critical_warning_committed", "intervention_failed",
    "evacuation_unavailable", "rescue_exhausted", "all_party_exposed",
})
POLICY_FIELDS = frozenset({
    "trigger_numerator", "trigger_denominator", "check_every_world_advances",
    "minimum_gap_world_advances", "maximum_per_chapter", "maximum_active",
})
EVENT_FIELDS = frozenset({
    "event_ref", "region_ref", "public_warning", "response_window_rounds",
    "terminal_conditions", "terminal_outcome", "source_refs",
    "response_actions", "failure_epilogue",
})
_REF = re.compile(r"^[a-z][a-z0-9_.:-]{0,159}$")


class TerminalRiskContractError(ValueError):
    def __init__(self, code: str, path: str):
        self.code, self.path = code, path
        super().__init__(f"{code}:{path}")


def _fail(code: str, path: str) -> None:
    raise TerminalRiskContractError(code, path)


def _object(value: Any, fields: set[str] | frozenset[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _fail("terminal_risk.fields_invalid", path)
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail("terminal_risk.value_invalid", path)
    return value


def _ref(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        _fail("terminal_risk.reference_invalid", path)
    return value


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def compile_terminal_risk_catalog(document: Mapping[str, Any], event_refs: set[str]) -> dict[str, Any]:
    source = _object(document, {"schema", "story_pack_ref", "candidate_version", "installable", "policy", "events", "flow_bindings"}, "catalog")
    if source["schema"] != AUTHOR_SCHEMA or source["candidate_version"] != "unassigned" or source["installable"] is not False:
        _fail("terminal_risk.identity_invalid", "catalog")
    pack_ref = _ref(source["story_pack_ref"], "catalog.story_pack_ref")
    policy = dict(_object(source["policy"], POLICY_FIELDS, "catalog.policy"))
    denominator = _integer(policy["trigger_denominator"], "policy.trigger_denominator", 1, 1_000_000)
    _integer(policy["trigger_numerator"], "policy.trigger_numerator", 0, denominator)
    for field in ("check_every_world_advances", "minimum_gap_world_advances", "maximum_per_chapter"):
        _integer(policy[field], "policy."+field, 1, 10_000)
    if policy["maximum_active"] != 1 or isinstance(policy["maximum_active"], bool):
        _fail("terminal_risk.active_limit_invalid", "policy.maximum_active")
    if not isinstance(source["events"], list) or not 1 <= len(source["events"]) <= 1000:
        _fail("terminal_risk.events_invalid", "catalog.events")
    events = []
    seen: set[str] = set()
    for index, raw in enumerate(source["events"]):
        path = f"catalog.events[{index}]"
        item = dict(_object(raw, EVENT_FIELDS, path))
        ref = _ref(item["event_ref"], path+".event_ref")
        if ref in seen or ref not in event_refs:
            _fail("terminal_risk.event_unresolved", path+".event_ref")
        seen.add(ref)
        _ref(item["region_ref"], path+".region_ref")
        warning = item["public_warning"]
        if not isinstance(warning, str) or not 20 <= len(warning.strip()) <= 1200:
            _fail("terminal_risk.warning_invalid", path+".public_warning")
        _integer(item["response_window_rounds"], path+".response_window_rounds", 2, 100)
        required = item["terminal_conditions"]
        if not isinstance(required, list) or any(not isinstance(x, str) for x in required) or len(required) != len(CONDITIONS) or set(required) != CONDITIONS:
            _fail("terminal_risk.conditions_invalid", path+".terminal_conditions")
        if item["terminal_outcome"] != "party_wipe":
            _fail("terminal_risk.outcome_invalid", path+".terminal_outcome")
        refs = item["source_refs"]
        if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x or len(x)>500 or x.startswith(("/", "\\")) or ".." in x.split("/") for x in refs):
            _fail("terminal_risk.source_invalid", path+".source_refs")
        item["terminal_conditions"] = sorted(required)
        actions = item["response_actions"]
        if not isinstance(actions, list) or not 3 <= len(actions) <= item["response_window_rounds"]:
            _fail("terminal_risk.actions_invalid", path+".response_actions")
        seen_actions = set()
        groups = set()
        for action in actions:
            _object(action, {"action_ref", "condition", "label", "ability_ref", "difficulty", "resolution_rule_ref", "modifier_formula"}, path+".response_actions")
            formula = _object(action['modifier_formula'], {'kind', 'baseline'}, path+'.response_actions.modifier_formula')
            if formula['kind'] != 'attribute_minus_baseline':
                _fail('terminal_risk.modifier_formula_invalid', path+'.response_actions.modifier_formula.kind')
            _integer(formula['baseline'], path+'.response_actions.modifier_formula.baseline', 0, 100)
            for key in ("action_ref", "ability_ref", "resolution_rule_ref"):
                _ref(action[key], path+".response_actions."+key)
            if action["action_ref"] in seen_actions or action["condition"] not in {"intervention_failed", "evacuation_unavailable", "rescue_exhausted"}:
                _fail("terminal_risk.actions_invalid", path+".response_actions")
            if not isinstance(action["label"], str) or not 1 <= len(action["label"].strip()) <= 120:
                _fail("terminal_risk.actions_invalid", path+".response_actions.label")
            _integer(action["difficulty"], path+".response_actions.difficulty", 1, 100)
            seen_actions.add(action["action_ref"])
            groups.add(action["condition"])
        if len(groups) != 3:
            _fail("terminal_risk.actions_invalid", path+".response_actions")
        if not isinstance(item["failure_epilogue"], str) or not 20 <= len(item["failure_epilogue"].strip()) <= 1200:
            _fail("terminal_risk.epilogue_invalid", path+".failure_epilogue")
        events.append(item)
    flow_bindings=[]
    seen_flows=set()
    if not isinstance(source["flow_bindings"], list) or not 1 <= len(source["flow_bindings"]) <= 1000:
        _fail("terminal_risk.flow_binding_invalid", "flow_bindings")
    for index,raw in enumerate(source['flow_bindings']):
        binding=dict(_object(raw,{'recipe_ref','region_ref','chapter_ref'},f'flow_bindings[{index}]'))
        for name,value in binding.items():_ref(value,f'flow_bindings[{index}].{name}')
        if binding['recipe_ref'] in seen_flows or binding['region_ref'] not in {item['region_ref'] for item in events}:
            _fail('terminal_risk.flow_binding_invalid',f'flow_bindings[{index}]')
        seen_flows.add(binding['recipe_ref']);flow_bindings.append(binding)
    if not flow_bindings:_fail('terminal_risk.flow_binding_invalid','flow_bindings')
    result = {"schema": IR_SCHEMA, "story_pack_ref": pack_ref, "policy": policy, "flow_bindings":sorted(flow_bindings,key=lambda x:x['recipe_ref']),
              "events": sorted(events, key=lambda item:item["event_ref"]), "author_sha256": _digest(source)}
    return {**result, "ir_sha256": _digest(result)}


def validate_terminal_risk_ir(ir: Mapping[str, Any]) -> None:
    _object(ir, {"schema", "story_pack_ref", "policy", "events", "flow_bindings", "author_sha256", "ir_sha256"}, "ir")
    if ir["schema"] != IR_SCHEMA or ir["ir_sha256"] != _digest({key:value for key,value in ir.items() if key != "ir_sha256"}):
        _fail("terminal_risk.digest_invalid", "ir")
    if not isinstance(ir["events"], list) or not ir["events"] or any(not isinstance(item,Mapping) or not isinstance(item.get('event_ref'),str) for item in ir['events']):
        _fail("terminal_risk.events_invalid", "ir.events")
    reconstructed = {"schema":AUTHOR_SCHEMA, "story_pack_ref":ir["story_pack_ref"], "candidate_version":"unassigned",
                     "installable":False, "policy":ir["policy"], "events":ir["events"], "flow_bindings":ir['flow_bindings']}
    compiled = compile_terminal_risk_catalog(reconstructed, {item["event_ref"] for item in ir["events"]})
    if compiled["events"] != ir["events"] or compiled["flow_bindings"] != ir["flow_bindings"] or not isinstance(ir["author_sha256"], str) or re.fullmatch(r"sha256:[0-9a-f]{64}", ir["author_sha256"]) is None:
        _fail("terminal_risk.ir_invalid", "ir")


def evaluate_terminal_conditions(ir: Mapping[str, Any], event_ref: str, conditions: Mapping[str, bool]) -> dict[str, Any]:
    validate_terminal_risk_ir(ir)
    item = next((entry for entry in ir["events"] if entry["event_ref"] == event_ref), None)
    if item is None:
        _fail("terminal_risk.event_unresolved", "event_ref")
    _object(conditions, CONDITIONS, "conditions")
    if any(type(value) is not bool for value in conditions.values()):
        _fail("terminal_risk.condition_type_invalid", "conditions")
    missing = sorted(name for name in CONDITIONS if not conditions[name])
    return {"schema":"se-terminal-risk-decision/1.0.0", "event_ref":event_ref, "ir_sha256":ir["ir_sha256"],
            "decision":"continue" if missing else "terminal_candidate", "unmet_conditions":missing,
            "outcome":None if missing else item["terminal_outcome"], "committed":False, "model_calls":0}


class RemoteTerminalRiskEngine:
    """Public zero-model-call dispatcher over the platform's pinned risk IR."""
    contract_version = "se-terminal-risk-remote-dispatch/1.0.0"

    def __init__(self, ir: Mapping[str, Any]):
        validate_terminal_risk_ir(ir)
        self._ir=json.loads(json.dumps(ir,ensure_ascii=False,allow_nan=False))

    async def evaluate_terminal_risk(self, event_ref: str, conditions: Mapping[str,bool]) -> Mapping[str,Any]:
        return evaluate_terminal_conditions(self._ir,event_ref,conditions)

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: Any = None) -> Mapping[str, Any]:
        if method=='health':
            if payload:_fail('terminal_risk.fields_invalid','health.payload')
            return {'status':'alive','contract_version':self.contract_version,'ir_sha256':self._ir['ir_sha256']}
        if method!='evaluate_terminal_risk':_fail('terminal_risk.method_unsupported','method')
        _object(payload,{'event_ref','conditions'},'request')
        return evaluate_terminal_conditions(self._ir,payload['event_ref'],payload['conditions'])


def create_remote_terminal_risk_engine(*, artifact: Mapping[str, Any], artifact_ref: str) -> RemoteTerminalRiskEngine:
    from .v02_extension_candidate import normalize_v02_extension_candidate
    if not isinstance(artifact_ref,str) or not artifact_ref or not isinstance(artifact,Mapping):
        _fail('terminal_risk.artifact_invalid','artifact')
    extension=normalize_v02_extension_candidate(artifact.get('v02_extension',{}))
    ir=extension['products'].get('terminal_risk')
    if not isinstance(ir,Mapping) or ir.get('story_pack_ref')!=artifact.get('package',{}).get('package_id'):
        _fail('terminal_risk.artifact_binding_invalid','artifact.v02_extension')
    rules = {item['resolution_rule_ref'] for item in artifact.get('resolution_rule_definitions', [])}
    if any(action['resolution_rule_ref'] not in rules for event in ir['events'] for action in event['response_actions']):
        _fail('terminal_risk.response_rule_unresolved', 'artifact.resolution_rule_definitions')
    return RemoteTerminalRiskEngine(ir)


def create_embedded_terminal_risk_engine(*, artifact: Mapping[str, Any], artifact_ref: str) -> RemoteTerminalRiskEngine:
    return create_remote_terminal_risk_engine(artifact=artifact,artifact_ref=artifact_ref)
