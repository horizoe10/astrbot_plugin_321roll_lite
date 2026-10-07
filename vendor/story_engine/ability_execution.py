"""Trusted ability definitions and proposal-only execution contracts."""
from __future__ import annotations
from collections.abc import Mapping,Sequence
from dataclasses import dataclass,replace
from datetime import UTC,datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any,Protocol
from .contracts.port import CancellationCheck,OperationEnvelope,PlatformBridge,PortContractError,Problem,ProblemCode,canonical_fingerprint,freeze_json

ABILITY_EXECUTION_CAPABILITY="ability.execution/1.0.0";ABILITY_AUTHOR_SCHEMA="se-ability-execution-definitions/1.0.0"
ABILITY_SNAPSHOT_SCHEMA="se-ability-execution-snapshot/1.0.0";ABILITY_REQUEST_SCHEMA="se-ability-execution-evaluation/1.0.0";ABILITY_PROPOSAL_SCHEMA="se-ability-execution-proposal/1.0.0";ABILITY_RESULT_SCHEMA="se-ability-execution-result/1.0.0"
_GRANTS=frozenset({"ignore","auto","selected","conditional"});_TARGETS=frozenset({"actor","objective","threat","zone"});_OPS=frozenset({"create_instance","modify","remove_instance"});_ACTION_KINDS=frozenset({"aid","cast","guard","interact","maneuver","parley","retreat","strike"})
class AbilityExecutionContractError(ValueError):
 def __init__(self,c,p,r):self.code,self.path,self.reason=c,p,r;super().__init__(f"{c}:{p}")
def _fail(c,p,r):raise AbilityExecutionContractError(c,p,r)
def _text(v,p,n=512):
 if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("ability.text_invalid",p,"bounded text required")
 return v.strip()
def _ref(v,p):
 r=_text(v,p,160)
 if not r[0].isalnum() or any(not(c.isalnum() or c in "_.:@-") for c in r):_fail("ability.ref_invalid",p,"opaque ref required")
 return r
def _hash(v,p):
 r=_text(v,p,71)
 if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("ability.hash_invalid",p,"sha256 required")
 return r
def _map(v,p):
 if not isinstance(v,Mapping):_fail("ability.object_invalid",p,"object required")
 return v
def _seq(v,p):
 if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("ability.array_invalid",p,"array required")
 return v
def _plain(v):
 if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
 if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
 return v
def compile_ability_execution_definitions(doc):
 if not isinstance(doc,Mapping) or set(doc)!={"schema","source_authority","resource_definitions_sha256","runtime_effects_sha256","policies","definitions"} or doc.get("schema")!=ABILITY_AUTHOR_SCHEMA:_fail("ability.document_invalid","$","document invalid")
 source=_map(doc["source_authority"],"source_authority")
 if set(source)!={"path","digest_algorithm","digest"} or source["digest_algorithm"]!="canonical-json-utf8-v1":_fail("ability.source_invalid","source_authority","source invalid")
 for key in ("digest",):_hash(source[key],key)
 for key in ("resource_definitions_sha256","runtime_effects_sha256"):_hash(doc[key],key)
 policies=_map(doc["policies"],"policies")
 if set(policies)!={"cooldown_available","charges_available","interrupt_available","refund_policy"} or any(policies[x] is not False for x in ("cooldown_available","charges_available","interrupt_available")) or policies["refund_policy"]!="before_commit_only":_fail("ability.policy_unsupported","policies","unregistered cooldown/charges/interrupt unavailable")
 out=[];seen=set()
 for i,raw in enumerate(_seq(doc["definitions"],"definitions")):
  p=f"definitions[{i}]";v=_map(raw,p);fields={"ability_ref","label","description","capability_type_ref","narrative_only","grant_policy","tags","targeting","costs","check_modifier","effects","failure_forward","action_kinds","usage_constraints"}
  if set(v)!=fields:_fail("ability.definition_fields_invalid",p,"fields invalid")
  ref=_ref(v["ability_ref"],p)
  if ref in seen or v["grant_policy"] not in _GRANTS or not isinstance(v["narrative_only"],bool):_fail("ability.definition_invalid",p,"identity/policy invalid")
  target=_map(v["targeting"],p)
  if set(target)!={"entity_types","minimum","maximum"}:_fail("ability.targeting_invalid",p,"targeting fields invalid")
  entity=[str(x) for x in _seq(target["entity_types"],p)];minimum,maximum=target["minimum"],target["maximum"]
  if any(x not in _TARGETS for x in entity) or len(entity)!=len(set(entity)) or any(isinstance(x,bool) or not isinstance(x,int) for x in (minimum,maximum)) or not 0<=minimum<=maximum<=8 or (maximum==0)!=(not entity):_fail("ability.targeting_invalid",p,"targeting invalid")
  costs=[]
  for cost in _seq(v["costs"],p):
   c=_map(cost,p)
   if set(c)!={"resource_ref","operation","value","persistence_scope","resource_definition_sha256"} or c["operation"]!="subtract" or isinstance(c["value"],bool) or not isinstance(c["value"],int) or c["value"]<=0 or c["persistence_scope"] not in {"character","scene","campaign"}:_fail("ability.cost_invalid",p,"cost invalid")
   costs.append({"resource_ref":_ref(c["resource_ref"],p),"operation":"subtract","value":c["value"],"persistence_scope":c["persistence_scope"],"resource_definition_sha256":_hash(c["resource_definition_sha256"],p)})
  effects=[]
  for effect in _seq(v["effects"],p):
   e=_map(effect,p)
   fields={"effect_ref","effect_kind","effect_definition_sha256","op","target_ref","recipient_scope","persistence_scope","description","resource_ref","resource_definition_sha256","amount"}
   if set(e)!=fields or e["effect_kind"] not in {"runtime_effect","resource_delta"} or e["recipient_scope"] not in {"actor","target","room"} or e["persistence_scope"] not in {"scene","character","campaign"}:_fail("ability.effect_invalid",p,"effect invalid")
   if e["effect_kind"]=="runtime_effect":
    if e["op"] not in _OPS or e["target_ref"] is None or any(e[x] is not None for x in ("resource_ref","resource_definition_sha256","amount")):_fail("ability.effect_invalid",p,"runtime effect invalid")
   elif e["op"]!="add" or e["target_ref"] is not None or e["recipient_scope"]!="actor" or e["resource_ref"] is None or e["resource_definition_sha256"] is None or isinstance(e["amount"],bool) or not isinstance(e["amount"],int) or e["amount"]<=0:_fail("ability.effect_invalid",p,"resource delta invalid")
   effects.append({"effect_ref":_ref(e["effect_ref"],p),"effect_kind":e["effect_kind"],"effect_definition_sha256":_hash(e["effect_definition_sha256"],p),"op":e["op"],"target_ref":None if e["target_ref"] is None else _ref(e["target_ref"],p),"recipient_scope":e["recipient_scope"],"persistence_scope":e["persistence_scope"],"description":_text(e["description"],p),"resource_ref":None if e["resource_ref"] is None else _ref(e["resource_ref"],p),"resource_definition_sha256":None if e["resource_definition_sha256"] is None else _hash(e["resource_definition_sha256"],p),"amount":e["amount"]})
  check=_map(v["check_modifier"],p)
  if any(not isinstance(k,str) or not k or isinstance(x,bool) or not isinstance(x,int) for k,x in check.items()):_fail("ability.check_invalid",p,"check modifier invalid")
  actions=[_text(x,p,64) for x in _seq(v["action_kinds"],p)]
  if len(actions)!=len(set(actions)) or any(x not in _ACTION_KINDS for x in actions) or (not v["narrative_only"] and not actions):_fail("ability.action_kind_invalid",p,"action kinds invalid")
  constraints=list(_seq(v["usage_constraints"],p))
  if constraints:_fail("ability.usage_constraint_unsupported",p,"source declares no executable usage constraints")
  if len({x["resource_ref"] for x in costs})!=len(costs) or len({x["effect_ref"] for x in effects})!=len(effects):_fail("ability.mechanics_duplicate",p,"duplicate cost/effect")
  if v["narrative_only"] and (costs or effects or check or maximum):_fail("ability.narrative_authority_invalid",p,"narrative-only ability cannot claim mechanics")
  tags=[_text(x,p,128) for x in _seq(v["tags"],p)]
  if len(tags)!=len(set(tags)):_fail("ability.definition_invalid",p,"duplicate tags")
  item={"schema":"se-ability-execution-definition-ir/1.0.0","ability_ref":ref,"label":_text(v["label"],p),"description":_text(v["description"],p),"capability_type_ref":_ref(v["capability_type_ref"],p),"narrative_only":v["narrative_only"],"grant_policy":v["grant_policy"],"tags":sorted(tags),"targeting":{"entity_types":entity,"minimum":minimum,"maximum":maximum},"costs":costs,"check_modifier":_plain(check),"effects":effects,"failure_forward":_text(v["failure_forward"],p),"action_kinds":sorted(actions),"usage_constraints":constraints};item["definition_sha256"]=canonical_fingerprint(item);out.append(item);seen.add(ref)
 catalog={"schema":"se-ability-execution-catalog-ir/1.0.0","source_authority":_plain(source),"resource_definitions_sha256":doc["resource_definitions_sha256"],"runtime_effects_sha256":doc["runtime_effects_sha256"],"policies":_plain(policies),"definitions":sorted(out,key=lambda x:x["ability_ref"])};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog
def bind_ability_execution(extension,catalog):
 if not isinstance(extension,Mapping) or set(extension)!={"ability_refs"}:_fail("ability.extension_invalid","extension","ability_refs only")
 refs=[_ref(x,"ability_refs") for x in _seq(extension["ability_refs"],"ability_refs")];defs={x["ability_ref"]:x for x in catalog["definitions"]}
 if not refs or len(refs)!=len(set(refs)) or any(x not in defs for x in refs):_fail("ability.definition_unknown","ability_refs","unknown ability")
 return {"schema":"se-ability-execution-binding-ir/1.0.0","abilities":[{"ability_ref":x,"definition_sha256":defs[x]["definition_sha256"]} for x in refs]}

class AbilityAction(StrEnum):PREVIEW="preview";SELECT_TARGET="select_target";ACTIVATE="activate";CAST="cast";USE="use";CANCEL="cancel";INTERRUPT="interrupt";RESOLVE="resolve"
class AbilityStatus(StrEnum):PROPOSED="proposed";INVALID="invalid";BLOCKED="blocked";CANCELLED="cancelled";TIMED_OUT="timed_out"
class AbilityProposalKind(StrEnum):PREVIEW="preview";TARGETS="targets";EXECUTION="execution";CANCEL="cancel";VALIDATION="validation"
_EMPTY_ACTIONS=frozenset({AbilityAction.PREVIEW,AbilityAction.ACTIVATE,AbilityAction.CAST,AbilityAction.USE,AbilityAction.CANCEL,AbilityAction.INTERRUPT,AbilityAction.RESOLVE})
_PUBLIC_FIELDS={"ability_label","action","available","target_min","target_max","cost_count","effect_count","requires_check","refund_policy","outcome","message"}
_BASE_PRIVATE={"base_room_revision","base_actor_revision","base_ability_revision","actor_ref","ability_ref","definition_sha256","platform_commit_required"}
def _strict_int(v,p,minimum=0):
 if isinstance(v,bool) or not isinstance(v,int) or v<minimum:raise PortContractError(ProblemCode.INPUT_INVALID,p,"integer invalid")
 return v
def _exact_receipt(v,fields,schema,path):
 if not isinstance(v,Mapping) or set(v)!=fields or v.get("schema")!=schema or v.get("fingerprint")!=canonical_fingerprint({k:x for k,x in v.items() if k!="fingerprint"}):raise PortContractError(ProblemCode.INPUT_INVALID,path,"receipt invalid")
 return v
def _catalog_author(c):
 return {"schema":ABILITY_AUTHOR_SCHEMA,"source_authority":_plain(c["source_authority"]),"resource_definitions_sha256":c["resource_definitions_sha256"],"runtime_effects_sha256":c["runtime_effects_sha256"],"policies":_plain(c["policies"]),"definitions":[{k:_plain(v) for k,v in d.items() if k not in {"schema","definition_sha256"}} for d in c["definitions"]]}

@dataclass(frozen=True,slots=True)
class AbilitySnapshot:
 schema:str;room_ref:str;actor_ref:str;ability_ref:str;definition_sha256:str;room_revision:int;actor_revision:int;ability_revision:int;granted_ability_refs:tuple[str,...];resources:Mapping[str,Mapping[str,Any]];targets:Mapping[str,Mapping[str,Any]];selected_target_refs:tuple[str,...];pending_operation_ref:str|None;pending_committed:bool;permission_receipt:Mapping[str,Any];rule_receipt:Mapping[str,Any]|None;expected_session_revision:int;fingerprint:str
 def __post_init__(self):
  if self.schema!=ABILITY_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"ability_snapshot","schema invalid")
  for x in (self.room_ref,self.actor_ref,self.ability_ref):_ref(x,"snapshot.ref")
  _hash(self.definition_sha256,"definition_sha256");_hash(self.fingerprint,"fingerprint")
  for n in ("room_revision","actor_revision","ability_revision","expected_session_revision"):_strict_int(getattr(self,n),n)
  if not isinstance(self.pending_committed,bool):raise PortContractError(ProblemCode.INPUT_INVALID,"ability_snapshot","pending invalid")
  if self.pending_committed and self.pending_operation_ref is None:raise PortContractError(ProblemCode.INPUT_INVALID,"ability_snapshot","committed pending requires operation ref")
  if self.pending_operation_ref is not None:_ref(self.pending_operation_ref,"pending_operation_ref")
  for name in ("granted_ability_refs","selected_target_refs"):
   values=getattr(self,name)
   if not isinstance(values,tuple) or len(values)!=len(set(values)):
    raise PortContractError(ProblemCode.INPUT_INVALID,name,"refs invalid")
   for x in values:_ref(x,name)
  if not isinstance(self.resources,Mapping) or not isinstance(self.targets,Mapping) or not isinstance(self.permission_receipt,Mapping) or self.rule_receipt is not None and not isinstance(self.rule_receipt,Mapping):raise PortContractError(ProblemCode.INPUT_INVALID,"ability_snapshot","state invalid")
  for ref,state in self.resources.items():
   _ref(ref,"resources.ref")
   if not isinstance(state,Mapping) or set(state)!={"definition_sha256","value","revision"}:raise PortContractError(ProblemCode.INPUT_INVALID,"resources","resource shape invalid")
   _hash(state["definition_sha256"],"resources.definition_sha256");_strict_int(state["value"],"resources.value");_strict_int(state["revision"],"resources.revision")
  for ref,target in self.targets.items():
   _ref(ref,"targets.ref")
   if not isinstance(target,Mapping) or set(target)!={"entity_type","revision","label"} or target["entity_type"] not in _TARGETS:raise PortContractError(ProblemCode.INPUT_INVALID,"targets","target shape invalid")
   _strict_int(target["revision"],"targets.revision");_text(target["label"],"targets.label")
  pf={"schema","receipt_ref","actor_ref","room_ref","ability_ref","definition_sha256","actor_revision","room_revision","ability_revision","allowed_actions","expires_at","committed","fingerprint"}
  _exact_receipt(self.permission_receipt,pf,"platform-ability-permission-receipt/1.0.0","permission_receipt")
  for n in ("receipt_ref","actor_ref","room_ref","ability_ref"):_ref(self.permission_receipt[n],"permission_receipt."+n)
  _hash(self.permission_receipt["definition_sha256"],"permission_receipt.definition_sha256")
  for n in ("actor_revision","room_revision","ability_revision"):_strict_int(self.permission_receipt[n],"permission_receipt."+n)
  if self.permission_receipt["committed"] is not True:raise PortContractError(ProblemCode.INPUT_INVALID,"permission_receipt.committed","commit invalid")
  if not isinstance(self.permission_receipt["allowed_actions"],Sequence) or isinstance(self.permission_receipt["allowed_actions"],str) or len(self.permission_receipt["allowed_actions"])!=len(set(self.permission_receipt["allowed_actions"])) or any(x not in {a.value for a in AbilityAction} for x in self.permission_receipt["allowed_actions"]):raise PortContractError(ProblemCode.INPUT_INVALID,"permission_receipt.allowed_actions","actions invalid")
  try:
   if datetime.fromisoformat(str(self.permission_receipt["expires_at"]).replace("Z","+00:00")).tzinfo is None:raise ValueError
  except ValueError as exc:raise PortContractError(ProblemCode.INPUT_INVALID,"permission_receipt.expires_at","time invalid") from exc
  if self.rule_receipt is not None:
   rf={"schema","receipt_ref","operation_ref","room_ref","actor_ref","ability_ref","definition_sha256","room_revision","actor_revision","ability_revision","selected_target_refs","target_revisions","check_modifier","outcome","committed","fingerprint"};_exact_receipt(self.rule_receipt,rf,"platform-ability-rule-receipt/1.0.0","rule_receipt")
   for n in ("receipt_ref","operation_ref","room_ref","actor_ref","ability_ref"):_ref(self.rule_receipt[n],"rule_receipt."+n)
   _hash(self.rule_receipt["definition_sha256"],"rule_receipt.definition_sha256")
   for n in ("room_revision","actor_revision","ability_revision"):_strict_int(self.rule_receipt[n],"rule_receipt."+n)
   if not isinstance(self.rule_receipt["selected_target_refs"],Sequence) or isinstance(self.rule_receipt["selected_target_refs"],str) or len(self.rule_receipt["selected_target_refs"])!=len(set(self.rule_receipt["selected_target_refs"])) or not _target_patch_valid(self.rule_receipt["selected_target_refs"],self.rule_receipt["target_revisions"]) or not isinstance(self.rule_receipt["check_modifier"],Mapping) or any(not isinstance(k,str) or not k or isinstance(v,bool) or not isinstance(v,int) for k,v in self.rule_receipt["check_modifier"].items()) or self.rule_receipt["outcome"] not in {"success","failure"} or self.rule_receipt["committed"] is not True:raise PortContractError(ProblemCode.INPUT_INVALID,"rule_receipt","rule shape invalid")
  object.__setattr__(self,"resources",freeze_json(self.resources,"resources"));object.__setattr__(self,"targets",freeze_json(self.targets,"targets"));object.__setattr__(self,"permission_receipt",freeze_json(self.permission_receipt,"permission"));object.__setattr__(self,"rule_receipt",None if self.rule_receipt is None else freeze_json(self.rule_receipt,"rule"))
 def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"granted_ability_refs":list(self.granted_ability_refs),"resources":_plain(self.resources),"targets":_plain(self.targets),"selected_target_refs":list(self.selected_target_refs),"permission_receipt":_plain(self.permission_receipt),"rule_receipt":None if self.rule_receipt is None else _plain(self.rule_receipt)}
 def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def ability_snapshot_fingerprint(x):return canonical_fingerprint(x.material())
@dataclass(frozen=True,slots=True)
class AbilityRequest:
 schema:str;envelope:OperationEnvelope;action:AbilityAction;snapshot:AbilitySnapshot;input:Mapping[str,Any]
 def __post_init__(self):
  if self.schema!=ABILITY_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_ability_execution" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,AbilityAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"ability_request","request invalid")
  object.__setattr__(self,"input",freeze_json(self.input,"ability_input"))
def ability_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})

def _public_valid(v):
 return isinstance(v,Mapping) and set(v)==_PUBLIC_FIELDS and isinstance(v["ability_label"],str) and bool(v["ability_label"].strip()) and len(v["ability_label"])<=512 and v["action"] in {x.value for x in AbilityAction} and isinstance(v["available"],bool) and all(isinstance(v[x],int) and not isinstance(v[x],bool) and v[x]>=0 for x in ("target_min","target_max","cost_count","effect_count")) and isinstance(v["requires_check"],bool) and v["refund_policy"]=="before_commit_only" and v["outcome"] in {"none","pending","success","failure"} and isinstance(v["message"],str) and bool(v["message"].strip()) and len(v["message"])<=512
def _target_patch_valid(refs,revisions):
 if not isinstance(refs,Sequence) or isinstance(refs,(str,bytes)) or len(refs)!=len(set(refs)) or not isinstance(revisions,Mapping) or set(refs)!=set(revisions):return False
 try:
  for x in refs:_ref(x,"target_ref");_strict_int(revisions[x],"target_revision")
 except (AbilityExecutionContractError,PortContractError):return False
 return True
def _cost_patch_valid(x,fields):
 if not isinstance(x,Mapping) or set(x)!=fields:return False
 try:_ref(x["resource_ref"],"resource_ref");_hash(x["resource_definition_sha256"],"resource_hash");_strict_int(x["resource_revision"],"resource_revision");_strict_int(x["subtract"],"subtract",1);_strict_int(x["next_value"],"next_value")
 except (AbilityExecutionContractError,PortContractError):return False
 return True
def _effect_patch_valid(x,fields):
 if not isinstance(x,Mapping) or set(x)!=fields or x["effect_kind"] not in {"runtime_effect","resource_delta"} or x["recipient_scope"] not in {"actor","target","room"} or x["persistence_scope"] not in {"scene","character","campaign"}:return False
 try:_ref(x["effect_ref"],"effect_ref");_hash(x["effect_definition_sha256"],"effect_hash")
 except AbilityExecutionContractError:return False
 if x["effect_kind"]=="runtime_effect":
  try:_ref(x["target_ref"],"target_ref")
  except AbilityExecutionContractError:return False
  return x["op"] in _OPS and x["resource_ref"] is None and x["resource_definition_sha256"] is None and x["amount"] is None
 try:_ref(x["resource_ref"],"resource_ref");_hash(x["resource_definition_sha256"],"resource_hash");_strict_int(x["amount"],"amount",1)
 except (AbilityExecutionContractError,PortContractError):return False
 return x["op"]=="add" and x["target_ref"] is None and x["recipient_scope"]=="actor"
def _private_valid(kind,v):
 if kind is AbilityProposalKind.VALIDATION:return v is None
 if not isinstance(v,Mapping) or not _BASE_PRIVATE<=set(v) or v["platform_commit_required"] is not True:return False
 try:
  for x in ("base_room_revision","base_actor_revision","base_ability_revision"):_strict_int(v[x],x)
  _ref(v["actor_ref"],"actor_ref");_ref(v["ability_ref"],"ability_ref");_hash(v["definition_sha256"],"definition_sha256")
 except (PortContractError,AbilityExecutionContractError):return False
 exact={
  AbilityProposalKind.PREVIEW:_BASE_PRIVATE|{"read_only"},
  AbilityProposalKind.TARGETS:_BASE_PRIVATE|{"selected_target_refs","target_revisions"},
  AbilityProposalKind.CANCEL:_BASE_PRIVATE|{"cancel_operation_ref","refund_costs","effects_committed"},
  AbilityProposalKind.EXECUTION:_BASE_PRIVATE|{"phase","selected_target_refs","target_revisions","check_modifier","costs","effects","atomic_cost_effect","rule_receipt_ref","rule_outcome","cooldown","charges"},
 }[kind]
 if set(v)!=exact:return False
 if kind is AbilityProposalKind.PREVIEW:return v["read_only"] is True
 if kind is AbilityProposalKind.TARGETS:
  return _target_patch_valid(v["selected_target_refs"],v["target_revisions"])
 if kind is AbilityProposalKind.CANCEL:
  try:_ref(v["cancel_operation_ref"],"cancel_operation_ref")
  except AbilityExecutionContractError:return False
  return v["refund_costs"] is False and v["effects_committed"] is False
 if v["phase"] not in {"check_required","resolve_candidate"} or v["atomic_cost_effect"] is not True or v["cooldown"] is not None or v["charges"] is not None:return False
 if not isinstance(v["costs"],Sequence) or isinstance(v["costs"],str) or not isinstance(v["effects"],Sequence) or isinstance(v["effects"],str) or not _target_patch_valid(v["selected_target_refs"],v["target_revisions"]) or not isinstance(v["check_modifier"],Mapping) or any(not isinstance(k,str) or isinstance(x,bool) or not isinstance(x,int) for k,x in v["check_modifier"].items()):return False
 cost_fields={"resource_ref","resource_definition_sha256","resource_revision","subtract","next_value"};effect_fields={"effect_ref","effect_kind","effect_definition_sha256","op","target_ref","recipient_scope","persistence_scope","resource_ref","resource_definition_sha256","amount"}
 if any(not _cost_patch_valid(x,cost_fields) for x in v["costs"]) or any(not _effect_patch_valid(x,effect_fields) for x in v["effects"]) or len({x["resource_ref"] for x in v["costs"]})!=len(v["costs"]) or len({x["effect_ref"] for x in v["effects"]})!=len(v["effects"]):return False
 if v["rule_receipt_ref"] is not None:
  try:_ref(v["rule_receipt_ref"],"rule_receipt_ref")
  except AbilityExecutionContractError:return False
 return (v["phase"]=="check_required" and not v["effects"] and v["rule_receipt_ref"] is None and v["rule_outcome"] is None) or (v["phase"]=="resolve_candidate" and v["rule_outcome"] in {None,"success","failure"} and (v["rule_receipt_ref"] is None)==(v["rule_outcome"] is None))
@dataclass(frozen=True,slots=True)
class AbilityProposal:
 schema:str;proposal_ref:str;operation_ref:str;source_ability_revision:int;kind:AbilityProposalKind;public_preview:Mapping[str,Any];private_reconciliation:Mapping[str,Any]|None;validation_errors:tuple[str,...];requires_platform_commit:bool=True;commits_state:bool=False
 def __post_init__(self):
  if self.schema!=ABILITY_PROPOSAL_SCHEMA or self.requires_platform_commit is not True or self.commits_state is not False or not isinstance(self.kind,AbilityProposalKind) or not _public_valid(self.public_preview) or not _private_valid(self.kind,self.private_reconciliation) or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) or not x for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_proposal","proposal invalid")
  _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref");_strict_int(self.source_ability_revision,"source_ability_revision")
  if (self.kind is AbilityProposalKind.VALIDATION)!=(bool(self.validation_errors)):raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_proposal","validation mismatch")
  object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public"));object.__setattr__(self,"private_reconciliation",None if self.private_reconciliation is None else freeze_json(self.private_reconciliation,"private"))
@dataclass(frozen=True,slots=True)
class AbilityResult:
 schema:str;operation_ref:str;request_fingerprint:str;expected_revision:int;source_ability_revision:int;status:AbilityStatus;proposal:AbilityProposal|None=None;problems:tuple[Problem,...]=();result_fingerprint:str="sha256:"+"0"*64
 def __post_init__(self):
  if self.schema!=ABILITY_RESULT_SCHEMA or not isinstance(self.status,AbilityStatus) or not isinstance(self.problems,tuple):raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_result","result invalid")
  if any(not isinstance(x,Problem) for x in self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_result.problems","problem invalid")
  _ref(self.operation_ref,"operation_ref");_hash(self.request_fingerprint,"request_fingerprint");_hash(self.result_fingerprint,"result_fingerprint");_strict_int(self.expected_revision,"expected_revision");_strict_int(self.source_ability_revision,"source_ability_revision")
  if self.status in {AbilityStatus.PROPOSED,AbilityStatus.INVALID}:
   if self.proposal is None or self.problems or self.proposal.operation_ref!=self.operation_ref or self.proposal.source_ability_revision!=self.source_ability_revision or (self.status is AbilityStatus.INVALID)!=(self.proposal.kind is AbilityProposalKind.VALIDATION):raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_result","proposal mismatch")
  elif self.proposal is not None or not self.problems:raise PortContractError(ProblemCode.OUTPUT_INVALID,"ability_result","terminal mismatch")
def ability_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_ability_revision":x.source_ability_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})

class AbilityExecutionEvaluator:
 def __init__(self,artifact):
  c=artifact.get("ability_execution_definitions")
  try:
   rebuilt=compile_ability_execution_definitions(_catalog_author(c)) if isinstance(c,Mapping) else None
  except (AbilityExecutionContractError,KeyError,TypeError):rebuilt=None
  if rebuilt is None or _plain(rebuilt)!=_plain(c):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"ability_catalog","catalog semantic invalid")
  self.definitions=MappingProxyType({x["ability_ref"]:freeze_json(x,"ability") for x in c["definitions"]});self.policies=freeze_json(c["policies"],"policies")
 def _state_problem(self,r,d):
  s=r.snapshot
  if s.fingerprint!=ability_snapshot_fingerprint(s):return "snapshot fingerprint stale"
  if d is None or d["definition_sha256"]!=s.definition_sha256 or s.ability_ref not in s.granted_ability_refs:return "ability not granted/definition mismatch"
  if len(s.granted_ability_refs)!=len(set(s.granted_ability_refs)) or any(x not in self.definitions for x in s.granted_ability_refs):return "grant snapshot invalid"
  for ref,state in s.resources.items():
   try:_ref(ref,"resource_ref")
   except AbilityExecutionContractError:return "resource ref invalid"
   if not isinstance(state,Mapping) or set(state)!={"definition_sha256","value","revision"}:return "resource snapshot invalid"
   try:_hash(state["definition_sha256"],"resource hash");_strict_int(state["value"],"resource value");_strict_int(state["revision"],"resource revision")
   except (AbilityExecutionContractError,PortContractError):return "resource snapshot invalid"
  for ref,target in s.targets.items():
   try:_ref(ref,"target_ref")
   except AbilityExecutionContractError:return "target ref invalid"
   if not isinstance(target,Mapping) or set(target)!={"entity_type","revision","label"} or target["entity_type"] not in _TARGETS or not isinstance(target["label"],str) or not target["label"]:return "target snapshot invalid"
   try:_strict_int(target["revision"],"target revision")
   except PortContractError:return "target snapshot invalid"
  if any(x not in s.targets for x in s.selected_target_refs):return "selected target unknown"
  pf={"schema","receipt_ref","actor_ref","room_ref","ability_ref","definition_sha256","actor_revision","room_revision","ability_revision","allowed_actions","expires_at","committed","fingerprint"}
  try:p=_exact_receipt(s.permission_receipt,pf,"platform-ability-permission-receipt/1.0.0","permission")
  except PortContractError:return "permission receipt invalid"
  if p["actor_ref"]!=s.actor_ref or p["room_ref"]!=s.room_ref or p["ability_ref"]!=s.ability_ref or p["definition_sha256"]!=s.definition_sha256 or (p["actor_revision"],p["room_revision"],p["ability_revision"])!=(s.actor_revision,s.room_revision,s.ability_revision) or p["committed"] is not True or not isinstance(p["allowed_actions"],Sequence) or isinstance(p["allowed_actions"],str) or len(p["allowed_actions"])!=len(set(p["allowed_actions"])) or any(x not in {a.value for a in AbilityAction} for x in p["allowed_actions"]):return "permission receipt identity invalid"
  try:
   if datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))>datetime.fromisoformat(str(p["expires_at"]).replace("Z","+00:00")):return "permission expires before operation"
  except ValueError:return "permission expiry invalid"
  return None
 def evaluate(self,r):
  s=r.snapshot;d=self.definitions.get(s.ability_ref)
  if r.envelope.request_fingerprint!=ability_request_fingerprint(r):return self._blocked(r,ProblemCode.RESULT_STALE,"request fingerprint stale")
  problem=self._state_problem(r,d)
  if problem:return self._blocked(r,ProblemCode.RESULT_STALE,problem)
  shapes={a:set() for a in _EMPTY_ACTIONS};shapes[AbilityAction.SELECT_TARGET]={"target_refs"}
  if set(r.input)!=shapes[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action shape invalid")
  if r.action.value not in s.permission_receipt["allowed_actions"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action not permitted")
  outcome="none";message=d["description"]
  public={"ability_label":d["label"],"action":r.action.value,"available":not d["narrative_only"],"target_min":d["targeting"]["minimum"],"target_max":d["targeting"]["maximum"],"cost_count":len(d["costs"]),"effect_count":len(d["effects"]),"requires_check":bool(d["check_modifier"]),"refund_policy":self.policies["refund_policy"],"outcome":outcome,"message":message}
  base={"base_room_revision":s.room_revision,"base_actor_revision":s.actor_revision,"base_ability_revision":s.ability_revision,"actor_ref":s.actor_ref,"ability_ref":s.ability_ref,"definition_sha256":s.definition_sha256,"platform_commit_required":True}
  if r.action is AbilityAction.PREVIEW:return self._proposal(r,AbilityProposalKind.PREVIEW,public,{**base,"read_only":True})
  if s.pending_operation_ref is not None and r.action is not AbilityAction.CANCEL:return self._blocked(r,ProblemCode.RESULT_STALE,"pending ability operation must be reconciled before a new proposal")
  if d["narrative_only"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"narrative-only ability has no executable mechanics")
  if r.action is AbilityAction.INTERRUPT:return self._blocked(r,ProblemCode.INPUT_INVALID,"interrupt unavailable")
  if r.action is AbilityAction.SELECT_TARGET:
   refs=r.input["target_refs"]
   if not isinstance(refs,Sequence) or isinstance(refs,(str,bytes)) or not all(isinstance(x,str) for x in refs) or len(refs)!=len(set(refs)) or not d["targeting"]["minimum"]<=len(refs)<=d["targeting"]["maximum"] or any(x not in s.targets or s.targets[x]["entity_type"] not in d["targeting"]["entity_types"] for x in refs):return self._invalid(r,public,"targets_invalid")
   return self._proposal(r,AbilityProposalKind.TARGETS,public,{**base,"selected_target_refs":list(refs),"target_revisions":{x:s.targets[x]["revision"] for x in refs}})
  if r.action is AbilityAction.CANCEL:
   if s.pending_operation_ref is None or s.pending_committed:return self._blocked(r,ProblemCode.RESULT_STALE,"nothing cancellable")
   return self._proposal(r,AbilityProposalKind.CANCEL,public,{**base,"cancel_operation_ref":s.pending_operation_ref,"refund_costs":False,"effects_committed":False})
  if r.action in {AbilityAction.ACTIVATE,AbilityAction.CAST,AbilityAction.USE,AbilityAction.RESOLVE}:
   if r.action is AbilityAction.CAST and "cast" not in d["action_kinds"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"cast not declared")
   refs=s.selected_target_refs
   if not d["targeting"]["minimum"]<=len(refs)<=d["targeting"]["maximum"] or any(x not in s.targets or s.targets[x]["entity_type"] not in d["targeting"]["entity_types"] for x in refs):return self._invalid(r,public,"targets_required")
   costs=[]
   for cost in d["costs"]:
    state=s.resources.get(cost["resource_ref"])
    if state is None or state["definition_sha256"]!=cost["resource_definition_sha256"] or state["value"]<cost["value"]:return self._invalid(r,public,"cost_unavailable")
    costs.append({"resource_ref":cost["resource_ref"],"resource_definition_sha256":cost["resource_definition_sha256"],"resource_revision":state["revision"],"subtract":cost["value"],"next_value":state["value"]-cost["value"]})
   private={**base,"selected_target_refs":list(refs),"target_revisions":{x:s.targets[x]["revision"] for x in refs},"check_modifier":_plain(d["check_modifier"]),"costs":costs,"effects":[],"atomic_cost_effect":True,"rule_receipt_ref":None,"rule_outcome":None,"cooldown":None,"charges":None}
   if d["check_modifier"]:
    if s.rule_receipt is None:
     public={**public,"outcome":"pending","message":"Platform check required before resolution."};return self._proposal(r,AbilityProposalKind.EXECUTION,public,{**private,"phase":"check_required"})
    fields={"schema","receipt_ref","operation_ref","room_ref","actor_ref","ability_ref","definition_sha256","room_revision","actor_revision","ability_revision","selected_target_refs","target_revisions","check_modifier","outcome","committed","fingerprint"}
    try:rr=_exact_receipt(s.rule_receipt,fields,"platform-ability-rule-receipt/1.0.0","rule_receipt")
    except PortContractError:return self._blocked(r,ProblemCode.INPUT_INVALID,"rule receipt invalid")
    if rr["operation_ref"]!=r.envelope.operation_ref or rr["room_ref"]!=s.room_ref or rr["actor_ref"]!=s.actor_ref or rr["ability_ref"]!=s.ability_ref or rr["definition_sha256"]!=s.definition_sha256 or (rr["room_revision"],rr["actor_revision"],rr["ability_revision"])!=(s.room_revision,s.actor_revision,s.ability_revision) or list(rr["selected_target_refs"])!=list(refs) or _plain(rr["target_revisions"])!={x:s.targets[x]["revision"] for x in refs} or _plain(rr["check_modifier"])!=_plain(d["check_modifier"]) or rr["outcome"] not in {"success","failure"} or rr["committed"] is not True:return self._blocked(r,ProblemCode.INPUT_INVALID,"rule receipt identity invalid")
    private.update(rule_receipt_ref=rr["receipt_ref"],rule_outcome=rr["outcome"]);outcome=rr["outcome"]
   effects=d["effects"] if outcome!="failure" else []
   private.update(phase="resolve_candidate",effects=[{k:v for k,v in e.items() if k!="description"} for e in effects])
   public={**public,"outcome":outcome,"message":d["failure_forward"] if outcome=="failure" else d["description"]}
   return self._proposal(r,AbilityProposalKind.EXECUTION,public,private)
  raise AssertionError("unreachable ability action")
 def _proposal(self,r,kind,public,private,status=AbilityStatus.PROPOSED,errors=()):
  p=AbilityProposal(ABILITY_PROPOSAL_SCHEMA,"ability."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.ability_revision,kind,public,private,tuple(errors));x=AbilityResult(ABILITY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.ability_revision,status,p,result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=ability_result_fingerprint(x))
 def _invalid(self,r,public,error):return self._proposal(r,AbilityProposalKind.VALIDATION,public,None,AbilityStatus.INVALID,(error,))
 def _blocked(self,r,code,reason):
  p=Problem(code,"evaluate ability execution",reason,"no proposal committed","refresh ability snapshot");x=AbilityResult(ABILITY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.ability_revision,AbilityStatus.BLOCKED,problems=(p,),result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=ability_result_fingerprint(x))
def decode_ability_snapshot(v):
 v=freeze_json(v,"ability_snapshot")
 if set(v)!=set(AbilitySnapshot.__dataclass_fields__) or not isinstance(v["granted_ability_refs"],tuple) or not isinstance(v["selected_target_refs"],tuple):raise ValueError("snapshot invalid")
 return AbilitySnapshot(**dict(v))
def decode_ability_request(v):
 v=freeze_json(v,"ability_request")
 if set(v)!={"schema","envelope","action","snapshot","input"}:raise ValueError("request invalid")
 return AbilityRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),AbilityAction(str(v["action"])),decode_ability_snapshot(v["snapshot"]),v["input"])
def decode_ability_result(v):
 v=freeze_json(v,"ability_result")
 if set(v)!=set(AbilityResult.__dataclass_fields__) or not isinstance(v["problems"],tuple):raise ValueError("result invalid")
 p=v["proposal"];proposal=None
 if p is not None:
  if not isinstance(p,Mapping) or set(p)!=set(AbilityProposal.__dataclass_fields__):raise ValueError("proposal invalid")
  proposal=AbilityProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_ability_revision"],AbilityProposalKind(str(p["kind"])),p["public_preview"],p["private_reconciliation"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["commits_state"])
 problems=[]
 for x in v["problems"]:
  if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__) or not isinstance(x["retryable"],bool):raise ValueError("problem invalid")
  problems.append(Problem(ProblemCode(str(x["code"])),x["failed_operation"],x["reason"],x["automatic_handling"],x["next_action"],x["retryable"]))
 r=AbilityResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_ability_revision"],AbilityStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
 if r.result_fingerprint!=ability_result_fingerprint(r):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","mismatch")
 return r
class AbilityExecutionService:
 def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
 async def evaluate_ability_execution(self,r,bridge):
  c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);deadline=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,AbilityStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,AbilityStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  x=self.evaluator.evaluate(r)
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,AbilityStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,AbilityStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  return x
 def _terminal(self,r,status,code):
  p=Problem(code,"evaluate ability execution","cancelled/deadline","no proposal","retry fresh");x=AbilityResult(ABILITY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.ability_revision,status,problems=(p,),result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=ability_result_fingerprint(x))
class AbilityExecutionStoryEnginePort(Protocol):
 async def evaluate_ability_execution(self,request:AbilityRequest,bridge:PlatformBridge)->AbilityResult:...
