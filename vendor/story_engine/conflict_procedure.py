"""System-neutral, proposal-only conflict procedure contracts."""
from __future__ import annotations
from collections.abc import Mapping,Sequence
from dataclasses import dataclass,replace
from datetime import UTC,datetime
from enum import StrEnum
from re import fullmatch
from types import MappingProxyType
from typing import Any,Protocol
from .contracts.port import CancellationCheck,OperationEnvelope,PlatformBridge,PortContractError,Problem,ProblemCode,canonical_fingerprint,freeze_json

CONFLICT_PROCEDURE_CAPABILITY="conflict.procedure/1.0.0"
CONFLICT_AUTHOR_SCHEMA="se-conflict-procedure-definitions/1.0.0"
CONFLICT_SNAPSHOT_SCHEMA="se-conflict-procedure-snapshot/1.0.0"
CONFLICT_REQUEST_SCHEMA="se-conflict-procedure-evaluation/1.0.0"
CONFLICT_PROPOSAL_SCHEMA="se-conflict-procedure-proposal/1.0.0"
CONFLICT_RESULT_SCHEMA="se-conflict-procedure-result/1.0.0"
_KINDS=frozenset({"combat","chase","contest","opposition","nonviolent"})
_ACTIONS=frozenset({"enter","act","assist","react","negotiate","retreat","surrender","resolve","aftermath"})
_OUTCOMES=frozenset({"continue","resolved","withdrawn","surrendered","stalemate","needs_rescue_or_fate"})
_EXIT_OUTCOMES=frozenset({"resolved","withdrawn","surrendered","stalemate","human_dm"})
_NONVIOLENT_ACTIONS=frozenset({"negotiate","retreat","surrender"})
_ENGAGEMENT=frozenset({"active","withdrawn","surrendered"});_OBJECTIVE_STATES=frozenset({"active","achieved","failed","withdrawn"})
class ConflictProcedureContractError(ValueError):
 def __init__(self,c,p,r):self.code,self.path,self.reason=c,p,r;super().__init__(f"{c}:{p}")
def _fail(c,p,r):raise ConflictProcedureContractError(c,p,r)
def _text(v,p,n=512):
 if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("conflict.text_invalid",p,"bounded text required")
 return v.strip()
def _ref(v,p):
 r=_text(v,p,160)
 if fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}",r) is None:_fail("conflict.ref_invalid",p,"ASCII opaque ref required")
 return r
def _hash(v,p):
 r=_text(v,p,71)
 if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("conflict.hash_invalid",p,"sha256 required")
 return r
def _map(v,p):
 if not isinstance(v,Mapping):_fail("conflict.object_invalid",p,"object required")
 return v
def _seq(v,p):
 if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("conflict.array_invalid",p,"array required")
 return v
def _plain(v):
 if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
 if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
 return v
def _strict_int(v,p,minimum=0):
 if isinstance(v,bool) or not isinstance(v,int) or v<minimum:raise PortContractError(ProblemCode.INPUT_INVALID,p,"integer invalid")
 return v
def compile_conflict_procedure_definitions(doc):
 if not isinstance(doc,Mapping) or set(doc)!={"schema","source_authority","definitions"} or doc.get("schema")!=CONFLICT_AUTHOR_SCHEMA:_fail("conflict.document_invalid","$","document invalid")
 source=_map(doc["source_authority"],"source_authority")
 if set(source)!={"path","digest_algorithm","digest"} or source["digest_algorithm"]!="canonical-json-utf8-v1":_fail("conflict.source_invalid","source_authority","source invalid")
 _text(source["path"],"source_authority.path",512);_hash(source["digest"],"source_authority.digest")
 out=[];seen=set();raw_definitions=_seq(doc["definitions"],"definitions")
 if not raw_definitions:_fail("conflict.document_invalid","definitions","at least one definition required")
 for i,raw in enumerate(raw_definitions):
  p=f"definitions[{i}]";v=_map(raw,p);fields={"procedure_ref","label","description","conflict_kinds","participant_roles","objective_policy","phase_order","windows","priority_policy","exit_policy","aftermath_policy"}
  if set(v)!=fields:_fail("conflict.definition_fields_invalid",p,"definition fields invalid")
  ref=_ref(v["procedure_ref"],p)
  if ref in seen:_fail("conflict.definition_duplicate",p,"duplicate procedure")
  kinds=[_text(x,p,32) for x in _seq(v["conflict_kinds"],p)]
  if not kinds or len(kinds)!=len(set(kinds)) or any(x not in _KINDS for x in kinds):_fail("conflict.kind_invalid",p,"conflict kinds invalid")
  roles=[];role_refs=set()
  for raw_role in _seq(v["participant_roles"],p):
   role=_map(raw_role,p)
   if set(role)!={"role_ref","label"}:_fail("conflict.role_invalid",p,"role fields invalid")
   rr=_ref(role["role_ref"],p)
   if rr in role_refs:_fail("conflict.role_invalid",p,"duplicate role")
   roles.append({"role_ref":rr,"label":_text(role["label"],p)});role_refs.add(rr)
  if len(roles)<2:_fail("conflict.role_invalid",p,"at least two roles required")
  phases=[_ref(x,p) for x in _seq(v["phase_order"],p)]
  if len(phases)<3 or len(phases)!=len(set(phases)):_fail("conflict.phase_invalid",p,"ordered unique phases required")
  windows=[];window_refs=set()
  for raw_window in _seq(v["windows"],p):
   w=_map(raw_window,p)
   if set(w)!={"window_ref","phase_ref","eligible_role_refs","allowed_actions","reaction_allowed"}:_fail("conflict.window_invalid",p,"window fields invalid")
   wr=_ref(w["window_ref"],p);phase=_ref(w["phase_ref"],p);eligible=[_ref(x,p) for x in _seq(w["eligible_role_refs"],p)];actions=[_text(x,p,32) for x in _seq(w["allowed_actions"],p)]
   if wr in window_refs or phase not in phases or not eligible or len(eligible)!=len(set(eligible)) or any(x not in role_refs for x in eligible) or not actions or len(actions)!=len(set(actions)) or any(x not in _ACTIONS for x in actions) or not isinstance(w["reaction_allowed"],bool):_fail("conflict.window_invalid",p,"window semantics invalid")
   windows.append({"window_ref":wr,"phase_ref":phase,"eligible_role_refs":eligible,"allowed_actions":actions,"reaction_allowed":w["reaction_allowed"]});window_refs.add(wr)
  if not windows or set(phases)-{x["phase_ref"] for x in windows}:_fail("conflict.window_invalid",p,"every phase requires a window")
  exit_policy=_map(v["exit_policy"],p);aftermath=_map(v["aftermath_policy"],p)
  if set(exit_policy)!={"outcomes","nonviolent_actions","vitality_depletion","terminal_owner"}:_fail("conflict.exit_policy_invalid",p,"exit policy fields invalid")
  outcomes=[_text(x,p,32) for x in _seq(exit_policy["outcomes"],p)];nonviolent=[_text(x,p,32) for x in _seq(exit_policy["nonviolent_actions"],p)]
  if len(outcomes)!=len(set(outcomes)) or set(outcomes)!=_EXIT_OUTCOMES or len(nonviolent)!=len(set(nonviolent)) or set(nonviolent)!=_NONVIOLENT_ACTIONS or any(action not in {a for window in windows for a in window["allowed_actions"]} for action in nonviolent) or exit_policy["vitality_depletion"]!="signal_only" or exit_policy["terminal_owner"]!="fate_rescue_owner":_fail("conflict.exit_policy_invalid",p,"exact nonviolent/fate boundary required")
  exit_policy={**exit_policy,"outcomes":outcomes,"nonviolent_actions":nonviolent}
  if set(aftermath)!={"cause_receipt_required","permanent_consequence_owner"} or aftermath["cause_receipt_required"] is not True or aftermath["permanent_consequence_owner"]!="321_platform":_fail("conflict.aftermath_policy_invalid",p,"platform cause owner required")
  if v["objective_policy"]!="platform_snapshot" or v["priority_policy"]!="platform_committed_receipt":_fail("conflict.authority_policy_invalid",p,"platform authority required")
  item={"schema":"se-conflict-procedure-definition-ir/1.0.0","procedure_ref":ref,"label":_text(v["label"],p),"description":_text(v["description"],p),"conflict_kinds":sorted(kinds),"participant_roles":roles,"objective_policy":v["objective_policy"],"phase_order":phases,"windows":windows,"priority_policy":v["priority_policy"],"exit_policy":_plain(exit_policy),"aftermath_policy":_plain(aftermath)};item["definition_sha256"]=canonical_fingerprint(item);out.append(item);seen.add(ref)
 catalog={"schema":"se-conflict-procedure-catalog-ir/1.0.0","source_authority":_plain(source),"definitions":sorted(out,key=lambda x:x["procedure_ref"])};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog
def bind_conflict_procedure(extension,catalog):
 if not isinstance(extension,Mapping) or set(extension)!={"procedure_ref"}:_fail("conflict.extension_invalid","extension","procedure_ref only")
 ref=_ref(extension["procedure_ref"],"procedure_ref");defs={x["procedure_ref"]:x for x in catalog["definitions"]}
 if ref not in defs:_fail("conflict.definition_unknown","procedure_ref","unknown procedure")
 return {"schema":"se-conflict-procedure-binding-ir/1.0.0","procedure_ref":ref,"definition_sha256":defs[ref]["definition_sha256"]}
def _catalog_author(c):return {"schema":CONFLICT_AUTHOR_SCHEMA,"source_authority":_plain(c["source_authority"]),"definitions":[{k:_plain(v) for k,v in d.items() if k not in {"schema","definition_sha256"}} for d in c["definitions"]]}
class ConflictAction(StrEnum):PREVIEW="preview";ENTER="enter";ACT="act";ASSIST="assist";REACT="react";NEGOTIATE="negotiate";RETREAT="retreat";SURRENDER="surrender";RESOLVE="resolve";AFTERMATH="aftermath";CANCEL="cancel"
class ConflictStatus(StrEnum):PROPOSED="proposed";INVALID="invalid";BLOCKED="blocked";CANCELLED="cancelled";TIMED_OUT="timed_out"
class ConflictProposalKind(StrEnum):PREVIEW="preview";INTENT="intent";NEXT_WINDOW="next_window";EXIT="exit";AFTERMATH="aftermath";CANCEL="cancel";VALIDATION="validation"
def _exact_receipt(v,fields,schema,path):
 if not isinstance(v,Mapping) or set(v)!=fields or v.get("schema")!=schema or v.get("committed") is not True or v.get("fingerprint")!=canonical_fingerprint({k:x for k,x in v.items() if k!="fingerprint"}):raise PortContractError(ProblemCode.INPUT_INVALID,path,"receipt invalid")
 return v
@dataclass(frozen=True,slots=True)
class ConflictSnapshot:
 schema:str;conflict_ref:str;procedure_ref:str;definition_sha256:str;room_ref:str;conflict_revision:int;room_revision:int;phase_ref:str;participants:Mapping[str,Mapping[str,Any]];objectives:Mapping[str,Mapping[str,Any]];priority_order:tuple[str,...];current_priority_index:int;current_window_ref:str;current_window_revision:int;window_receipt:Mapping[str,Any];resolution_receipt:Mapping[str,Any]|None;pending_operation_ref:str|None;pending_committed:bool;expected_session_revision:int;fingerprint:str
 def __post_init__(self):
  if self.schema!=CONFLICT_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"conflict_snapshot","schema invalid")
  for x in (self.conflict_ref,self.procedure_ref,self.room_ref,self.phase_ref,self.current_window_ref):_ref(x,"snapshot.ref")
  _hash(self.definition_sha256,"definition_sha256");_hash(self.fingerprint,"fingerprint")
  for n in ("conflict_revision","room_revision","current_priority_index","current_window_revision","expected_session_revision"):_strict_int(getattr(self,n),n)
  if not isinstance(self.pending_committed,bool):raise PortContractError(ProblemCode.INPUT_INVALID,"pending","pending flag invalid")
  if self.pending_operation_ref is not None:_ref(self.pending_operation_ref,"pending_operation_ref")
  if not isinstance(self.priority_order,tuple) or len(self.priority_order)<2 or len(self.priority_order)!=len(set(self.priority_order)) or self.current_priority_index>=len(self.priority_order):raise PortContractError(ProblemCode.INPUT_INVALID,"priority_order","priority invalid")
  if not isinstance(self.participants,Mapping) or not isinstance(self.objectives,Mapping):raise PortContractError(ProblemCode.INPUT_INVALID,"conflict_snapshot","state invalid")
  if len(self.participants)<2 or len(self.objectives)<1:raise PortContractError(ProblemCode.INPUT_INVALID,"conflict_snapshot","at least two participants and one objective required")
  for actor,state in self.participants.items():
   _ref(actor,"participant.actor");
   if not isinstance(state,Mapping) or set(state)!={"side_ref","role_ref","actor_revision","resource_revision","status_revision","engagement"} or state["engagement"] not in _ENGAGEMENT:raise PortContractError(ProblemCode.INPUT_INVALID,"participants","participant invalid")
   _ref(state["side_ref"],"side_ref");_ref(state["role_ref"],"role_ref")
   for n in ("actor_revision","resource_revision","status_revision"):_strict_int(state[n],n)
  if set(self.priority_order)!=set(self.participants):raise PortContractError(ProblemCode.INPUT_INVALID,"priority_order","participants mismatch")
  for objective,state in self.objectives.items():
   _ref(objective,"objective_ref")
   if not isinstance(state,Mapping) or set(state)!={"side_ref","label","revision","status"} or state["status"] not in _OBJECTIVE_STATES:raise PortContractError(ProblemCode.INPUT_INVALID,"objectives","objective invalid")
   _ref(state["side_ref"],"side_ref");_text(state["label"],"objective.label");_strict_int(state["revision"],"objective.revision")
  wf={"schema","receipt_ref","conflict_ref","procedure_ref","definition_sha256","room_ref","conflict_revision","room_revision","phase_ref","window_ref","window_revision","actor_ref","allowed_actions","participant_revisions","objective_revisions","committed","fingerprint"};wr=_exact_receipt(self.window_receipt,wf,"platform-conflict-window-receipt/1.0.0","window_receipt")
  for n in ("receipt_ref","conflict_ref","procedure_ref","room_ref","phase_ref","window_ref","actor_ref"):_ref(wr[n],"window_receipt."+n)
  _hash(wr["definition_sha256"],"window_receipt.definition_sha256")
  for n in ("conflict_revision","room_revision","window_revision"):_strict_int(wr[n],"window_receipt."+n)
  if not isinstance(wr["allowed_actions"],Sequence) or isinstance(wr["allowed_actions"],str) or len(wr["allowed_actions"])!=len(set(wr["allowed_actions"])) or any(x not in _ACTIONS for x in wr["allowed_actions"]):raise PortContractError(ProblemCode.INPUT_INVALID,"window_receipt.allowed_actions","actions invalid")
  for name in ("participant_revisions","objective_revisions"):
   if not isinstance(wr[name],Mapping):raise PortContractError(ProblemCode.INPUT_INVALID,"window_receipt."+name,"revision map invalid")
   for ref,revision in wr[name].items():_ref(ref,"window_receipt."+name);_strict_int(revision,"window_receipt."+name)
  if self.resolution_receipt is not None:
   rf={"schema","receipt_ref","operation_ref","conflict_ref","procedure_ref","definition_sha256","room_ref","conflict_revision","room_revision","phase_ref","window_ref","window_revision","actor_ref","action","outcome","signals","committed","fingerprint"};rr=_exact_receipt(self.resolution_receipt,rf,"platform-conflict-resolution-receipt/1.0.0","resolution_receipt")
   for n in ("receipt_ref","operation_ref","conflict_ref","procedure_ref","room_ref","phase_ref","window_ref","actor_ref"):_ref(rr[n],"resolution_receipt."+n)
   _hash(rr["definition_sha256"],"resolution_receipt.definition_sha256")
   for n in ("conflict_revision","room_revision","window_revision"):_strict_int(rr[n],"resolution_receipt."+n)
   if rr["action"] not in _ACTIONS or rr["outcome"] not in _OUTCOMES or not isinstance(rr["signals"],Sequence) or isinstance(rr["signals"],str) or len(rr["signals"])!=len(set(rr["signals"])):raise PortContractError(ProblemCode.INPUT_INVALID,"resolution_receipt","resolution invalid")
   for signal in rr["signals"]:_ref(signal,"resolution_receipt.signal")
  idle=self.pending_operation_ref is None and self.pending_committed is False and self.resolution_receipt is None
  pending=self.pending_operation_ref is not None and self.pending_committed is False and self.resolution_receipt is None
  resolved=self.pending_operation_ref is not None and self.pending_committed is True and self.resolution_receipt is not None and self.resolution_receipt["operation_ref"]==self.pending_operation_ref
  if not (idle or pending or resolved):raise PortContractError(ProblemCode.INPUT_INVALID,"pending","pending/receipt truth table invalid")
  object.__setattr__(self,"participants",freeze_json(self.participants,"participants"));object.__setattr__(self,"objectives",freeze_json(self.objectives,"objectives"));object.__setattr__(self,"window_receipt",freeze_json(self.window_receipt,"window_receipt"));object.__setattr__(self,"resolution_receipt",None if self.resolution_receipt is None else freeze_json(self.resolution_receipt,"resolution_receipt"))
 def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"participants":_plain(self.participants),"objectives":_plain(self.objectives),"priority_order":list(self.priority_order),"window_receipt":_plain(self.window_receipt),"resolution_receipt":None if self.resolution_receipt is None else _plain(self.resolution_receipt)}
 def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def conflict_snapshot_fingerprint(x):return canonical_fingerprint(x.material())
@dataclass(frozen=True,slots=True)
class ConflictRequest:
 schema:str;envelope:OperationEnvelope;action:ConflictAction;snapshot:ConflictSnapshot;input:Mapping[str,Any]
 def __post_init__(self):
  if self.schema!=CONFLICT_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_conflict_procedure" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,ConflictAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"conflict_request","request invalid")
  target_actions={ConflictAction.ACT,ConflictAction.ASSIST,ConflictAction.REACT,ConflictAction.NEGOTIATE,ConflictAction.RETREAT,ConflictAction.SURRENDER}
  if self.action in target_actions:
   if set(self.input)!={"target_refs"} or not isinstance(self.input["target_refs"],Sequence) or isinstance(self.input["target_refs"],(str,bytes,bytearray)) or len(self.input["target_refs"])!=len(set(self.input["target_refs"])):raise PortContractError(ProblemCode.INPUT_INVALID,"conflict_input.target_refs","unique target refs required")
   for target in self.input["target_refs"]:_ref(target,"conflict_input.target_refs")
  elif self.input:raise PortContractError(ProblemCode.INPUT_INVALID,"conflict_input","empty input required")
  object.__setattr__(self,"input",freeze_json(self.input,"conflict_input"))
def conflict_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})
_PUBLIC={"procedure_label","action","phase_label","current_actor_label","available_actions","outcome","message","requires_rescue_or_fate_gate"}
_BASE={"base_conflict_revision","base_room_revision","base_window_revision","conflict_ref","procedure_ref","definition_sha256","platform_commit_required"}
def _public_valid(v):return isinstance(v,Mapping) and set(v)==_PUBLIC and all(isinstance(v[x],str) and v[x] for x in ("procedure_label","action","phase_label","current_actor_label","outcome","message")) and v["action"] in {x.value for x in ConflictAction} and v["outcome"] in {"none"}|_OUTCOMES|{"human_dm"} and isinstance(v["available_actions"],Sequence) and not isinstance(v["available_actions"],str) and len(v["available_actions"])==len(set(v["available_actions"])) and all(x in _ACTIONS for x in v["available_actions"]) and isinstance(v["requires_rescue_or_fate_gate"],bool)
def _private_valid(kind,v):
 if kind is ConflictProposalKind.VALIDATION:return v is None
 if not isinstance(v,Mapping) or not _BASE<=set(v) or v["platform_commit_required"] is not True:return False
 exact={ConflictProposalKind.PREVIEW:_BASE|{"read_only"},ConflictProposalKind.INTENT:_BASE|{"actor_ref","phase_ref","window_ref","action","target_refs","platform_resolution_required"},ConflictProposalKind.NEXT_WINDOW:_BASE|{"source_resolution_receipt_ref","next_phase_ref","next_window_ref","next_actor_ref","next_priority_index"},ConflictProposalKind.EXIT:_BASE|{"source_resolution_receipt_ref","outcome","exit_actor_ref","requires_rescue_or_fate_gate"},ConflictProposalKind.AFTERMATH:_BASE|{"source_resolution_receipt_ref","outcome","requires_platform_cause_commit"},ConflictProposalKind.CANCEL:_BASE|{"cancel_operation_ref","effects_committed"}}[kind]
 if set(v)!=exact:return False
 try:
  for n in ("base_conflict_revision","base_room_revision","base_window_revision"):_strict_int(v[n],n)
  for n in ("conflict_ref","procedure_ref"):_ref(v[n],n)
  _hash(v["definition_sha256"],"definition_sha256")
  if kind is ConflictProposalKind.PREVIEW:return v["read_only"] is True
  if kind is ConflictProposalKind.INTENT:
   for n in ("actor_ref","phase_ref","window_ref"):_ref(v[n],n)
   if v["action"] not in _ACTIONS or not isinstance(v["target_refs"],Sequence) or isinstance(v["target_refs"],(str,bytes,bytearray)) or len(v["target_refs"])!=len(set(v["target_refs"])) or v["platform_resolution_required"] is not True:return False
   for target in v["target_refs"]:_ref(target,"target_refs")
   return True
  if kind is ConflictProposalKind.NEXT_WINDOW:
   for n in ("source_resolution_receipt_ref","next_phase_ref","next_window_ref","next_actor_ref"):_ref(v[n],n)
   _strict_int(v["next_priority_index"],"next_priority_index");return True
  if kind is ConflictProposalKind.EXIT:
   _ref(v["source_resolution_receipt_ref"],"receipt_ref");_ref(v["exit_actor_ref"],"exit_actor_ref");return v["outcome"] in {"resolved","withdrawn","surrendered","stalemate","human_dm"} and isinstance(v["requires_rescue_or_fate_gate"],bool)
  if kind is ConflictProposalKind.AFTERMATH:
   _ref(v["source_resolution_receipt_ref"],"receipt_ref");return v["outcome"] in {"resolved","withdrawn","surrendered","stalemate","human_dm"} and v["requires_platform_cause_commit"] is True
  if kind is ConflictProposalKind.CANCEL:
   _ref(v["cancel_operation_ref"],"cancel_operation_ref");return v["effects_committed"] is False
 except (ConflictProcedureContractError,PortContractError):return False
 return False
@dataclass(frozen=True,slots=True)
class ConflictProposal:
 schema:str;proposal_ref:str;operation_ref:str;source_conflict_revision:int;kind:ConflictProposalKind;public_preview:Mapping[str,Any];private_reconciliation:Mapping[str,Any]|None;validation_errors:tuple[str,...];requires_platform_commit:bool=True;commits_state:bool=False
 def __post_init__(self):
  if self.schema!=CONFLICT_PROPOSAL_SCHEMA or self.requires_platform_commit is not True or self.commits_state is not False or not isinstance(self.kind,ConflictProposalKind) or not _public_valid(self.public_preview) or not _private_valid(self.kind,self.private_reconciliation) or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) or not x for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_proposal","proposal invalid")
  _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref");_strict_int(self.source_conflict_revision,"source_conflict_revision")
  if self.private_reconciliation is not None and self.private_reconciliation["base_conflict_revision"]!=self.source_conflict_revision:raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_proposal","private base revision mismatch")
  if (self.kind is ConflictProposalKind.VALIDATION)!=(bool(self.validation_errors)):raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_proposal","validation mismatch")
  object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public"));object.__setattr__(self,"private_reconciliation",None if self.private_reconciliation is None else freeze_json(self.private_reconciliation,"private"))
@dataclass(frozen=True,slots=True)
class ConflictResult:
 schema:str;operation_ref:str;request_fingerprint:str;expected_revision:int;source_conflict_revision:int;status:ConflictStatus;proposal:ConflictProposal|None=None;problems:tuple[Problem,...]=();result_fingerprint:str="sha256:"+"0"*64
 def __post_init__(self):
  if self.schema!=CONFLICT_RESULT_SCHEMA or not isinstance(self.status,ConflictStatus) or not isinstance(self.problems,tuple):raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_result","result invalid")
  _ref(self.operation_ref,"operation_ref");_hash(self.request_fingerprint,"request_fingerprint");_hash(self.result_fingerprint,"result_fingerprint");_strict_int(self.expected_revision,"expected_revision");_strict_int(self.source_conflict_revision,"source_conflict_revision")
  if self.status in {ConflictStatus.PROPOSED,ConflictStatus.INVALID}:
   if self.proposal is None or self.problems or self.proposal.operation_ref!=self.operation_ref or self.proposal.source_conflict_revision!=self.source_conflict_revision or (self.status is ConflictStatus.INVALID)!=(self.proposal.kind is ConflictProposalKind.VALIDATION):raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_result","proposal mismatch")
  elif self.proposal is not None or not self.problems:raise PortContractError(ProblemCode.OUTPUT_INVALID,"conflict_result","terminal mismatch")
def conflict_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_conflict_revision":x.source_conflict_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})
def validate_conflict_result_for_request(result,request):
 if result.operation_ref!=request.envelope.operation_ref or result.request_fingerprint!=request.envelope.request_fingerprint or result.expected_revision!=request.envelope.expected_revision or result.source_conflict_revision!=request.snapshot.conflict_revision:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","result/request identity mismatch")
 private=None if result.proposal is None else result.proposal.private_reconciliation
 if private is not None:
  expected=(request.snapshot.conflict_revision,request.snapshot.room_revision,request.snapshot.current_window_revision,request.snapshot.conflict_ref,request.snapshot.procedure_ref,request.snapshot.definition_sha256)
  actual=(private["base_conflict_revision"],private["base_room_revision"],private["base_window_revision"],private["conflict_ref"],private["procedure_ref"],private["definition_sha256"])
  if actual!=expected:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","private reconciliation source mismatch")
  kind=result.proposal.kind
  expected_kinds={
   ConflictAction.PREVIEW:{ConflictProposalKind.PREVIEW},ConflictAction.ENTER:{ConflictProposalKind.NEXT_WINDOW},
   ConflictAction.ACT:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},ConflictAction.ASSIST:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},
   ConflictAction.REACT:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},ConflictAction.NEGOTIATE:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},
   ConflictAction.RETREAT:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},ConflictAction.SURRENDER:{ConflictProposalKind.INTENT,ConflictProposalKind.VALIDATION},
   ConflictAction.RESOLVE:{ConflictProposalKind.NEXT_WINDOW,ConflictProposalKind.EXIT},ConflictAction.AFTERMATH:{ConflictProposalKind.AFTERMATH},ConflictAction.CANCEL:{ConflictProposalKind.CANCEL},
  }
  if kind not in expected_kinds[request.action]:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","proposal kind does not match request action")
  if kind is ConflictProposalKind.INTENT:
   actor=request.snapshot.priority_order[request.snapshot.current_priority_index]
   if (private["actor_ref"],private["phase_ref"],private["window_ref"],private["action"],tuple(private["target_refs"]))!=(actor,request.snapshot.phase_ref,request.snapshot.current_window_ref,request.action.value,tuple(request.input["target_refs"])):raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","intent source mismatch")
  elif kind is ConflictProposalKind.NEXT_WINDOW:
   receipt=request.snapshot.window_receipt if request.action is ConflictAction.ENTER else request.snapshot.resolution_receipt
   if receipt is None or private["source_resolution_receipt_ref"]!=receipt["receipt_ref"]:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","advance receipt source mismatch")
  elif kind in {ConflictProposalKind.EXIT,ConflictProposalKind.AFTERMATH}:
   receipt=request.snapshot.resolution_receipt
   if receipt is None or private["source_resolution_receipt_ref"]!=receipt["receipt_ref"]:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","exit receipt source mismatch")
   if kind is ConflictProposalKind.EXIT and private["exit_actor_ref"]!=request.snapshot.priority_order[request.snapshot.current_priority_index]:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","exit actor source mismatch")
  elif kind is ConflictProposalKind.CANCEL and private["cancel_operation_ref"]!=request.snapshot.pending_operation_ref:raise PortContractError(ProblemCode.RESULT_STALE,"conflict_result","cancel operation source mismatch")
 return result
class ConflictProcedureEvaluator:
 def __init__(self,artifact):
  c=artifact.get("conflict_procedure_definitions")
  try:rebuilt=compile_conflict_procedure_definitions(_catalog_author(c)) if isinstance(c,Mapping) else None
  except (ConflictProcedureContractError,KeyError,TypeError):rebuilt=None
  if rebuilt is None or _plain(rebuilt)!=_plain(c):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"conflict_catalog","catalog semantic invalid")
  self.definitions=MappingProxyType({x["procedure_ref"]:freeze_json(x,"conflict_definition") for x in c["definitions"]})
 def _window(self,d,s):
  matches=[(i,w) for i,w in enumerate(d["windows"]) if w["window_ref"]==s.current_window_ref]
  if len(matches)!=1:return None,None,"compiled window missing"
  index,window=matches[0]
  if window["phase_ref"]!=s.phase_ref:return None,None,"compiled phase/window mismatch"
  actor=s.priority_order[s.current_priority_index];participant=s.participants[actor]
  if participant["role_ref"] not in window["eligible_role_refs"] or participant["engagement"]!="active":return None,None,"current participant ineligible"
  return index,window,None
 def _resolution_problem(self,s,rr,actor):
  expected=(s.conflict_ref,s.procedure_ref,s.definition_sha256,s.room_ref,s.conflict_revision,s.room_revision,s.phase_ref,s.current_window_ref,s.current_window_revision,actor,s.pending_operation_ref)
  actual=(rr["conflict_ref"],rr["procedure_ref"],rr["definition_sha256"],rr["room_ref"],rr["conflict_revision"],rr["room_revision"],rr["phase_ref"],rr["window_ref"],rr["window_revision"],rr["actor_ref"],rr["operation_ref"])
  return None if actual==expected else "resolution receipt foreign/stale"
 def _next(self,d,s,current_window_index):
   candidates=[]
   current=d["windows"][current_window_index]
   candidates.extend((current,i) for i in range(s.current_priority_index+1,len(s.priority_order)))
   for window in d["windows"][current_window_index+1:]:candidates.extend((window,i) for i in range(len(s.priority_order)))
   if len(candidates)>len(s.priority_order)*len(d["windows"]):raise AssertionError("conflict priority scan bound exceeded")
   for window,index in candidates:
    actor=s.priority_order[index];participant=s.participants[actor]
    if participant["engagement"]=="active" and participant["role_ref"] in window["eligible_role_refs"]:return window["phase_ref"],window["window_ref"],actor,index
   return None
 def evaluate(self,r):
  s=r.snapshot;d=self.definitions.get(s.procedure_ref)
  if r.envelope.request_fingerprint!=conflict_request_fingerprint(r):return self._blocked(r,ProblemCode.RESULT_STALE,"request fingerprint stale")
  if s.fingerprint!=conflict_snapshot_fingerprint(s) or d is None or d["definition_sha256"]!=s.definition_sha256:return self._blocked(r,ProblemCode.RESULT_STALE,"snapshot/definition stale")
  wr=s.window_receipt;actor=s.priority_order[s.current_priority_index];window_index,window,window_problem=self._window(d,s)
  if window_problem:return self._blocked(r,ProblemCode.RESULT_STALE,window_problem)
  participant_revisions={x:y["actor_revision"] for x,y in s.participants.items()};objective_revisions={x:y["revision"] for x,y in s.objectives.items()}
  if (wr["conflict_ref"],wr["procedure_ref"],wr["definition_sha256"],wr["room_ref"],wr["conflict_revision"],wr["room_revision"],wr["phase_ref"],wr["window_ref"],wr["window_revision"],wr["actor_ref"])!=(s.conflict_ref,s.procedure_ref,s.definition_sha256,s.room_ref,s.conflict_revision,s.room_revision,s.phase_ref,s.current_window_ref,s.current_window_revision,actor) or _plain(wr["participant_revisions"])!=participant_revisions or _plain(wr["objective_revisions"])!=objective_revisions or list(wr["allowed_actions"])!=list(window["allowed_actions"]):return self._blocked(r,ProblemCode.RESULT_STALE,"window receipt stale")
  shapes={x:set() for x in ConflictAction};shapes.update({ConflictAction.ACT:{"target_refs"},ConflictAction.ASSIST:{"target_refs"},ConflictAction.REACT:{"target_refs"},ConflictAction.NEGOTIATE:{"target_refs"},ConflictAction.RETREAT:{"target_refs"},ConflictAction.SURRENDER:{"target_refs"}})
  if set(r.input)!=shapes[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action shape invalid")
  public={"procedure_label":d["label"],"action":r.action.value,"phase_label":s.phase_ref,"current_actor_label":"Current participant","available_actions":list(wr["allowed_actions"]),"outcome":"none","message":d["description"],"requires_rescue_or_fate_gate":False}
  base={"base_conflict_revision":s.conflict_revision,"base_room_revision":s.room_revision,"base_window_revision":s.current_window_revision,"conflict_ref":s.conflict_ref,"procedure_ref":s.procedure_ref,"definition_sha256":s.definition_sha256,"platform_commit_required":True}
  if r.action is ConflictAction.PREVIEW:return self._proposal(r,ConflictProposalKind.PREVIEW,public,{**base,"read_only":True})
  if r.action is ConflictAction.CANCEL:
   if s.pending_operation_ref is None or s.pending_committed or s.resolution_receipt is not None:return self._blocked(r,ProblemCode.RESULT_STALE,"nothing cancellable")
   return self._proposal(r,ConflictProposalKind.CANCEL,public,{**base,"cancel_operation_ref":s.pending_operation_ref,"effects_committed":False})
  if s.pending_operation_ref is not None and r.action not in {ConflictAction.RESOLVE,ConflictAction.AFTERMATH}:return self._blocked(r,ProblemCode.RESULT_STALE,"pending conflict operation requires exactly resolve/aftermath or cancel")
  if r.action is ConflictAction.ENTER:
   if "enter" not in window["allowed_actions"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"enter unavailable")
   next_state=self._next(d,s,window_index)
   if next_state is None:return self._blocked(r,ProblemCode.INPUT_INVALID,"no eligible next window")
   phase,window_ref,next_actor,index=next_state;return self._proposal(r,ConflictProposalKind.NEXT_WINDOW,public,{**base,"source_resolution_receipt_ref":wr["receipt_ref"],"next_phase_ref":phase,"next_window_ref":window_ref,"next_actor_ref":next_actor,"next_priority_index":index})
  if r.action in {ConflictAction.ACT,ConflictAction.ASSIST,ConflictAction.REACT,ConflictAction.NEGOTIATE,ConflictAction.RETREAT,ConflictAction.SURRENDER}:
   if r.action.value not in window["allowed_actions"] or r.action is ConflictAction.REACT and not window["reaction_allowed"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action not allowed in compiled window")
   targets=r.input["target_refs"]
   legal_targets={x for x,state in s.participants.items() if state["engagement"]=="active"}|{x for x,state in s.objectives.items() if state["status"]=="active"}
   if any(x not in legal_targets for x in targets):return self._invalid(r,public,"targets_invalid")
   return self._proposal(r,ConflictProposalKind.INTENT,public,{**base,"actor_ref":actor,"phase_ref":s.phase_ref,"window_ref":s.current_window_ref,"action":r.action.value,"target_refs":list(targets),"platform_resolution_required":True})
  if r.action is ConflictAction.RESOLVE:
   rr=s.resolution_receipt
   if rr is None or not s.pending_committed or self._resolution_problem(s,rr,actor) or rr["action"]=="aftermath" or rr["action"] not in window["allowed_actions"]:return self._blocked(r,ProblemCode.RESULT_STALE,"resolution receipt identity invalid")
   outcome=rr["outcome"];gate=outcome=="needs_rescue_or_fate" or "vitality_depleted" in rr["signals"]
   if not gate and outcome!="continue" and outcome not in d["exit_policy"]["outcomes"]:return self._blocked(r,ProblemCode.RESULT_STALE,"resolution outcome not declared by procedure")
   public={**public,"outcome":outcome,"requires_rescue_or_fate_gate":gate,"message":"Platform resolution received; platform commit remains required."}
   if outcome=="continue":
    next_state=self._next(d,s,window_index)
    if next_state is None:return self._blocked(r,ProblemCode.INPUT_INVALID,"no eligible next window")
    phase,window_ref,next_actor,index=next_state;return self._proposal(r,ConflictProposalKind.NEXT_WINDOW,public,{**base,"source_resolution_receipt_ref":rr["receipt_ref"],"next_phase_ref":phase,"next_window_ref":window_ref,"next_actor_ref":next_actor,"next_priority_index":index})
   mapped="human_dm" if gate else outcome
   return self._proposal(r,ConflictProposalKind.EXIT,public,{**base,"source_resolution_receipt_ref":rr["receipt_ref"],"outcome":mapped,"exit_actor_ref":actor,"requires_rescue_or_fate_gate":gate})
  if r.action is ConflictAction.AFTERMATH:
   rr=s.resolution_receipt
   if rr is None or not s.pending_committed or self._resolution_problem(s,rr,actor) or rr["action"]!="aftermath" or "aftermath" not in window["allowed_actions"] or rr["outcome"]=="continue":return self._blocked(r,ProblemCode.RESULT_STALE,"foreign/stale aftermath receipt")
   gate=rr["outcome"]=="needs_rescue_or_fate" or "vitality_depleted" in rr["signals"]
   if not gate and rr["outcome"] not in d["exit_policy"]["outcomes"]:return self._blocked(r,ProblemCode.RESULT_STALE,"aftermath outcome not declared by procedure")
   return self._proposal(r,ConflictProposalKind.AFTERMATH,{**public,"outcome":rr["outcome"],"requires_rescue_or_fate_gate":gate},{**base,"source_resolution_receipt_ref":rr["receipt_ref"],"outcome":"human_dm" if gate else rr["outcome"],"requires_platform_cause_commit":True})
  raise AssertionError("unreachable conflict action")
 def _proposal(self,r,kind,public,private,status=ConflictStatus.PROPOSED,errors=()):
  p=ConflictProposal(CONFLICT_PROPOSAL_SCHEMA,"conflict."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.conflict_revision,kind,public,private,tuple(errors));x=ConflictResult(CONFLICT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.conflict_revision,status,p,result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=conflict_result_fingerprint(x))
 def _invalid(self,r,public,error):return self._proposal(r,ConflictProposalKind.VALIDATION,public,None,ConflictStatus.INVALID,(error,))
 def _blocked(self,r,code,reason):
  p=Problem(code,"evaluate conflict procedure",reason,"no proposal committed","refresh conflict snapshot");x=ConflictResult(CONFLICT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.conflict_revision,ConflictStatus.BLOCKED,problems=(p,),result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=conflict_result_fingerprint(x))
def decode_conflict_snapshot(v):
 v=freeze_json(v,"conflict_snapshot")
 if set(v)!=set(ConflictSnapshot.__dataclass_fields__) or not isinstance(v["priority_order"],tuple):raise ValueError("snapshot invalid")
 return ConflictSnapshot(**dict(v))
def decode_conflict_request(v):
 v=freeze_json(v,"conflict_request")
 if set(v)!={"schema","envelope","action","snapshot","input"}:raise ValueError("request invalid")
 return ConflictRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),ConflictAction(str(v["action"])),decode_conflict_snapshot(v["snapshot"]),v["input"])
def decode_conflict_result(v):
 v=freeze_json(v,"conflict_result")
 if set(v)!=set(ConflictResult.__dataclass_fields__) or not isinstance(v["problems"],tuple):raise ValueError("result invalid")
 p=v["proposal"];proposal=None
 if p is not None:
  if not isinstance(p,Mapping) or set(p)!=set(ConflictProposal.__dataclass_fields__) or not isinstance(p["validation_errors"],tuple) or not isinstance(p["requires_platform_commit"],bool) or not isinstance(p["commits_state"],bool):raise ValueError("proposal invalid")
  proposal=ConflictProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_conflict_revision"],ConflictProposalKind(str(p["kind"])),p["public_preview"],p["private_reconciliation"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["commits_state"])
 problems=[]
 for x in v["problems"]:
  if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__) or not isinstance(x["retryable"],bool):raise ValueError("problem invalid")
  problems.append(Problem(ProblemCode(str(x["code"])),x["failed_operation"],x["reason"],x["automatic_handling"],x["next_action"],x["retryable"]))
 result=ConflictResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_conflict_revision"],ConflictStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
 if result.result_fingerprint!=conflict_result_fingerprint(result):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","mismatch")
 return result
class ConflictProcedureService:
 def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
 async def evaluate_conflict_procedure(self,r,bridge):
  c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);deadline=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,ConflictStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,ConflictStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  x=self.evaluator.evaluate(r)
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,ConflictStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,ConflictStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  return x
 def _terminal(self,r,status,code):
  p=Problem(code,"evaluate conflict procedure","cancelled/deadline","no proposal","retry fresh");x=ConflictResult(CONFLICT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.conflict_revision,status,problems=(p,),result_fingerprint="sha256:"+"0"*64);return replace(x,result_fingerprint=conflict_result_fingerprint(x))
class ConflictProcedureStoryEnginePort(Protocol):
 async def evaluate_conflict_procedure(self,request:ConflictRequest,bridge:PlatformBridge)->ConflictResult:...
