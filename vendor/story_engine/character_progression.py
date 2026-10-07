"""Receipt-bound, proposal-only character progression."""
from __future__ import annotations
from collections.abc import Mapping,Sequence
from dataclasses import dataclass,replace
from datetime import UTC,datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any,Protocol
from .contracts.port import CancellationCheck,OperationEnvelope,PlatformBridge,PortContractError,Problem,ProblemCode,canonical_fingerprint,freeze_json

CHARACTER_PROGRESSION_CAPABILITY="character.progression/1.0.0"
CHARACTER_PROGRESSION_AUTHOR_SCHEMA="se-character-progression-definitions/1.0.0"
CHARACTER_PROGRESSION_SNAPSHOT_SCHEMA="se-character-progression-snapshot/1.0.0"
CHARACTER_PROGRESSION_REQUEST_SCHEMA="se-character-progression-evaluation/1.0.0"
CHARACTER_PROGRESSION_PROPOSAL_SCHEMA="se-character-progression-proposal/1.0.0"
CHARACTER_PROGRESSION_RESULT_SCHEMA="se-character-progression-result/1.0.0"
_MODELS=frozenset({"none","xp","level","milestone","rank","mixed"});_TRACK_KINDS=frozenset({"xp","level","milestone","rank"})
class CharacterProgressionContractError(ValueError):
 def __init__(self,code,path,reason):self.code,self.path,self.reason=code,path,reason;super().__init__(f"{code}:{path}")
def _fail(c,p,r):raise CharacterProgressionContractError(c,p,r)
def _text(v,p,n=240):
 if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("progression.text_invalid",p,"必须是有界非空文本。")
 return v.strip()
def _ref(v,p):
 r=_text(v,p,128)
 if not r[0].isalnum() or any(not(c.isalnum() or c in "_.:@-") for c in r):_fail("progression.ref_invalid",p,"必须是 opaque ref。")
 return r
def _hash(v,p):
 r=_text(v,p,71)
 if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("progression.hash_invalid",p,"必须是 SHA-256。")
 return r
def _seq(v,p):
 if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("progression.array_invalid",p,"必须是数组。")
 return v
def _map(v,p):
 if not isinstance(v,Mapping):_fail("progression.object_invalid",p,"必须是对象。")
 return v
def _plain(v):
 if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
 if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
 return v

def compile_character_progression_definitions(document):
 if set(document)!={"schema","definitions"} or document.get("schema")!=CHARACTER_PROGRESSION_AUTHOR_SCHEMA:_fail("progression.document_invalid","$","作者文档无效。")
 if not isinstance(document["definitions"],Sequence) or not document["definitions"]:_fail("progression.definitions_empty","definitions","至少一个 definition。")
 out=[];seen=set()
 for i,raw in enumerate(document["definitions"]):
  p=f"definitions[{i}]";v=_map(raw,p);fields={"progression_ref","label","model","tracks","point_pools","unlocks","overflow_policy","defer_allowed","respec_policy"}
  if set(v)!=fields:_fail("progression.definition_fields_invalid",p,"字段缺失或未知。")
  ref=_ref(v["progression_ref"],p);model=str(v["model"])
  if ref in seen:_fail("progression.definition_duplicate",p,"progression_ref 重复。")
  if model not in _MODELS:_fail("progression.model_invalid",p,"model 无效。")
  seen.add(ref);tracks=[];track_refs=set();kinds=set()
  for j,item in enumerate(_seq(v["tracks"],p)):
   item=_map(item,p)
   if set(item)!={"track_ref","label","kind","starting_value","cap","thresholds"}:_fail("progression.track_invalid",p,"track 字段无效。")
   tr=_ref(item["track_ref"],p);kind=str(item["kind"]);start=item["starting_value"];cap=item["cap"]
   if tr in track_refs or kind not in _TRACK_KINDS or any(isinstance(x,bool) or not isinstance(x,int) for x in (start,cap)) or not 0<=start<=cap:_fail("progression.track_invalid",p,"track identity/kind/bounds 无效。")
   thresholds=[];last=-1
   for t in _seq(item["thresholds"],p):
    t=_map(t,p)
    if set(t)!={"value","label","grant_points"} or isinstance(t["value"],bool) or not isinstance(t["value"],int) or not last<t["value"]<=cap or not isinstance(t["grant_points"],Mapping) or any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in t["grant_points"].values()):_fail("progression.threshold_invalid",p,"threshold 必须递增且在 cap 内。")
    last=t["value"];thresholds.append({"value":t["value"],"label":_text(t["label"],p),"grant_points":_plain(t["grant_points"])})
   tracks.append({"track_ref":tr,"label":_text(item["label"],p),"kind":kind,"starting_value":start,"cap":cap,"thresholds":thresholds});track_refs.add(tr);kinds.add(kind)
  if model=="none" and tracks or model!="none" and not tracks or model in _TRACK_KINDS and kinds!={model} or model=="mixed" and len(kinds)<2:_fail("progression.model_tracks_mismatch",p,"model 与 tracks 不一致。")
  pools=[];pool_refs=set()
  for item in _seq(v["point_pools"],p):
   item=_map(item,p)
   if set(item)!={"pool_ref","label","cap","overflow"}:_fail("progression.pool_invalid",p,"point pool 字段无效。")
   pr=_ref(item["pool_ref"],p);cap=item["cap"]
   if pr in pool_refs or isinstance(cap,bool) or not isinstance(cap,int) or cap<0 or item["overflow"] not in {"discard","bank","block"}:_fail("progression.pool_invalid",p,"point pool 无效。")
   pool_refs.add(pr);pools.append({"pool_ref":pr,"label":_text(item["label"],p),"cap":cap,"overflow":item["overflow"]})
  if any(pool not in pool_refs for track in tracks for threshold in track["thresholds"] for pool in threshold["grant_points"]):_fail("progression.threshold_pool_unknown",p,"threshold grant_points 引用未知 pool。")
  unlocks=[];unlock_refs=set()
  for item in _seq(v["unlocks"],p):
   item=_map(item,p)
   if set(item)!={"unlock_ref","label","pool_ref","cost","requires","excludes"}:_fail("progression.unlock_invalid",p,"unlock 字段无效。")
   ur=_ref(item["unlock_ref"],p);pr=_ref(item["pool_ref"],p);cost=item["cost"];req=[_ref(x,p) for x in _seq(item["requires"],p)];exc=[_ref(x,p) for x in _seq(item["excludes"],p)]
   if ur in unlock_refs or pr not in pool_refs or isinstance(cost,bool) or not isinstance(cost,int) or cost<0 or len(req)!=len(set(req)) or len(exc)!=len(set(exc)) or set(req)&set(exc) or ur in req or ur in exc:_fail("progression.unlock_invalid",p,"unlock identity/cost/relations 无效。")
   unlock_refs.add(ur);unlocks.append({"unlock_ref":ur,"label":_text(item["label"],p),"pool_ref":pr,"cost":cost,"requires":req,"excludes":exc})
  if any(x not in unlock_refs for u in unlocks for x in (*u["requires"],*u["excludes"])):_fail("progression.unlock_relation_unknown",p,"unlock relation 未注册。")
  dependencies={u["unlock_ref"]:set(u["requires"]) for u in unlocks};pending=set(dependencies);resolved=set()
  while pending:
   ready={u for u in pending if dependencies[u]<=resolved}
   if not ready:_fail("progression.unlock_cycle",p,"unlock requires 形成循环。")
   resolved|=ready;pending-=ready
  overflow=v["overflow_policy"]
  if overflow not in {"discard","bank","block"} or not isinstance(v["defer_allowed"],bool):_fail("progression.policy_invalid",p,"overflow/defer policy 无效。")
  respec=_map(v["respec_policy"],p)
  if set(respec)!={"allowed","self_confirmation_required","gate_required","track_reallocation"} or not all(isinstance(respec[x],bool) for x in ("allowed","self_confirmation_required","gate_required")):_fail("progression.respec_policy_invalid",p,"永久 respec policy 字段无效。")
  reallocation=_map(respec["track_reallocation"],p)
  if set(reallocation)!={"allowed","track_refs","preserve_total"} or not isinstance(reallocation["allowed"],bool) or reallocation["preserve_total"] is not True:_fail("progression.respec_policy_invalid",p,"track reallocation 必须显式声明目标并保持总量。")
  reallocation_refs=[_ref(x,p) for x in _seq(reallocation["track_refs"],p)]
  if len(reallocation_refs)!=len(set(reallocation_refs)) or any(x not in track_refs for x in reallocation_refs) or reallocation["allowed"]!=bool(reallocation_refs) or (reallocation["allowed"] and not respec["allowed"]):_fail("progression.respec_policy_invalid",p,"track reallocation 目标必须唯一、已注册且仅在 respec 开启时使用。")
  if respec["allowed"] and not(respec["self_confirmation_required"] and respec["gate_required"]):_fail("progression.respec_policy_invalid",p,"永久 respec 必须本人确认并经过 gate。")
  respec={**_plain(respec),"track_reallocation":{**_plain(reallocation),"track_refs":reallocation_refs}}
  if model=="none" and (pools or unlocks or respec["allowed"]):_fail("progression.none_mechanics_invalid",p,"none model 不得声明 points/unlocks/respec。")
  material={"schema":"se-character-progression-definition-ir/1.0.0","progression_ref":ref,"label":_text(v["label"],p),"model":model,"tracks":tracks,"point_pools":pools,"unlocks":unlocks,"overflow_policy":overflow,"defer_allowed":v["defer_allowed"],"respec_policy":_plain(respec)};material["definition_sha256"]=canonical_fingerprint(material);out.append(material)
 catalog={"schema":"se-character-progression-catalog-ir/1.0.0","definitions":sorted(out,key=lambda x:x["progression_ref"])};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog
def bind_character_progression(extension,catalog):
 if set(extension)!={"progression_ref"}:_fail("progression.extension_invalid","extension","只能包含 progression_ref。")
 ref=_ref(extension["progression_ref"],"progression_ref");d=next((x for x in catalog["definitions"] if x["progression_ref"]==ref),None)
 if d is None:_fail("progression.definition_unknown","progression_ref","definition 未注册。")
 return {"schema":"se-character-progression-binding-ir/1.0.0","progression_ref":ref,"definition_sha256":d["definition_sha256"]}

@dataclass(frozen=True,slots=True)
class ProgressionSnapshot:
 schema:str;actor_ref:str;room_ref:str;progression_ref:str;definition_sha256:str;actor_revision:int;room_revision:int;progression_revision:int;track_values:Mapping[str,int];point_values:Mapping[str,int];bank_values:Mapping[str,int];unlocked_refs:tuple[str,...];consumed_cause_refs:tuple[str,...];consumed_dedupe_keys:tuple[str,...];expected_session_revision:int;fingerprint:str
 def __post_init__(self):
  if self.schema!=CHARACTER_PROGRESSION_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"progression_snapshot","schema 无效。")
  for n in ("actor_ref","room_ref","progression_ref"):_ref(getattr(self,n),n)
  _hash(self.definition_sha256,"definition_sha256");_hash(self.fingerprint,"fingerprint")
  if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.actor_revision,self.room_revision,self.progression_revision,self.expected_session_revision)):raise PortContractError(ProblemCode.INPUT_INVALID,"revision","revision 无效。")
  for m in (self.track_values,self.point_values,self.bank_values):
   if not isinstance(m,Mapping) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in m.items()):raise PortContractError(ProblemCode.INPUT_INVALID,"values","值必须是非负整数映射。")
  for vals in (self.unlocked_refs,self.consumed_cause_refs,self.consumed_dedupe_keys):
   if not isinstance(vals,tuple) or len(vals)!=len(set(vals)):raise PortContractError(ProblemCode.INPUT_INVALID,"refs","refs 必须唯一数组。")
   for value in vals:_ref(value,"snapshot.refs")
  object.__setattr__(self,"track_values",freeze_json(self.track_values,"track_values"));object.__setattr__(self,"point_values",freeze_json(self.point_values,"point_values"));object.__setattr__(self,"bank_values",freeze_json(self.bank_values,"bank_values"))
 def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"track_values":_plain(self.track_values),"point_values":_plain(self.point_values),"bank_values":_plain(self.bank_values),"unlocked_refs":list(self.unlocked_refs),"consumed_cause_refs":list(self.consumed_cause_refs),"consumed_dedupe_keys":list(self.consumed_dedupe_keys)}
 def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def progression_snapshot_fingerprint(x):return canonical_fingerprint(x.material())

class ProgressionAction(StrEnum):PREVIEW_GAIN="preview_gain";ADVANCE="advance";SPEND="spend";CHOOSE_UNLOCK="choose_unlock";DEFER="defer";RESPEC="respec"
@dataclass(frozen=True,slots=True)
class ProgressionRequest:
 schema:str;envelope:OperationEnvelope;action:ProgressionAction;snapshot:ProgressionSnapshot;input:Mapping[str,Any]
 def __post_init__(self):
  if self.schema!=CHARACTER_PROGRESSION_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_character_progression" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,ProgressionAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"progression_request","request 无效。")
  object.__setattr__(self,"input",freeze_json(self.input,"progression_input"))
def progression_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})

class ProgressionProposalKind(StrEnum):PREVIEW="preview";PROGRESSION="progression";UNLOCK="unlock";DEFER="defer";RESPEC_GATE="respec_gate";NO_CHANGE="no_change";VALIDATION="validation"
class ProgressionStatus(StrEnum):PROPOSED="proposed";INVALID="invalid";BLOCKED="blocked";CANCELLED="cancelled";TIMED_OUT="timed_out"
_PUBLIC_FIELDS={"model","source_kind","track_count","unlock_choices","defer_allowed","respec_available"}
_STATE_PRIVATE={"actor_ref","room_ref","base_actor_revision","base_room_revision","base_progression_revision","consume_cause","platform_commit_required"}
_ADVANCE_PRIVATE=_STATE_PRIVATE|{"cause_ref","receipt_ref","dedupe_key","set_track_values","set_point_values","set_bank_values","crossed_thresholds","overflow"}
_SPEND_PRIVATE=_STATE_PRIVATE|{"set_point_values"}
_UNLOCK_PRIVATE=_STATE_PRIVATE|{"append_unlock_ref","set_point_values"}
_DEFER_PRIVATE=_STATE_PRIVATE|{"cause_ref","receipt_ref","dedupe_key","deferred"}
_RESPEC_PRIVATE=_STATE_PRIVATE|{"respec_candidate","remove_unlock_refs","set_track_values","derived_refund_points","set_point_values","self_confirmed","gate_receipt_ref","respec_plan_sha256","permanent_change_committed"}
_NO_CHANGE_PRIVATE={"cause_ref","dedupe_key","reason","consume_cause","deferred","platform_commit_required"}
def _proposal_payload_valid(kind,public,private):
 if not isinstance(public,Mapping) or set(public)!=_PUBLIC_FIELDS or public.get("model") not in _MODELS or public.get("source_kind") not in {None,"reward","milestone","cause"} or any(isinstance(public.get(x),bool) or not isinstance(public.get(x),int) or public.get(x)<0 for x in ("track_count","unlock_choices")) or any(not isinstance(public.get(x),bool) for x in ("defer_allowed","respec_available")):return False
 if kind is ProgressionProposalKind.VALIDATION:return private is None
 if not isinstance(private,Mapping):return False
 fields=set(private)
 if kind in {ProgressionProposalKind.PREVIEW,ProgressionProposalKind.PROGRESSION}:valid_fields=fields==_ADVANCE_PRIVATE or fields==_SPEND_PRIVATE
 elif kind is ProgressionProposalKind.UNLOCK:valid_fields=fields==_UNLOCK_PRIVATE
 elif kind is ProgressionProposalKind.DEFER:valid_fields=fields==_DEFER_PRIVATE
 elif kind is ProgressionProposalKind.RESPEC_GATE:valid_fields=fields==_RESPEC_PRIVATE
 elif kind is ProgressionProposalKind.NO_CHANGE:valid_fields=fields==_NO_CHANGE_PRIVATE
 else:return False
 if not valid_fields:return False
 for key in fields&{"actor_ref","room_ref","cause_ref","receipt_ref","dedupe_key","append_unlock_ref","gate_receipt_ref"}:
  try:_ref(private[key],key)
  except CharacterProgressionContractError:return False
 for key in fields&{"respec_plan_sha256"}:
  try:_hash(private[key],key)
  except CharacterProgressionContractError:return False
 for key in fields&{"base_actor_revision","base_room_revision","base_progression_revision"}:
  if isinstance(private[key],bool) or not isinstance(private[key],int) or private[key]<0:return False
 for key in fields&{"consume_cause","platform_commit_required","deferred","respec_candidate","self_confirmed","permanent_change_committed"}:
  if not isinstance(private[key],bool):return False
 if "platform_commit_required" in private and private["platform_commit_required"] is not True or "permanent_change_committed" in private and private["permanent_change_committed"] is not False:return False
 for key in fields&{"set_track_values","set_point_values","set_bank_values","derived_refund_points"}:
  if not isinstance(private[key],Mapping) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in private[key].items()):return False
 if "remove_unlock_refs" in private and (not isinstance(private["remove_unlock_refs"],Sequence) or isinstance(private["remove_unlock_refs"],(str,bytes)) or len(private["remove_unlock_refs"])!=len(set(private["remove_unlock_refs"])) or any(not isinstance(x,str) for x in private["remove_unlock_refs"])):return False
 if "crossed_thresholds" in private and (not isinstance(private["crossed_thresholds"],Sequence) or isinstance(private["crossed_thresholds"],(str,bytes)) or any(not isinstance(x,Mapping) or set(x)!={"track_ref","value"} or isinstance(x["value"],bool) or not isinstance(x["value"],int) or x["value"]<0 for x in private["crossed_thresholds"])):return False
 if "overflow" in private and (not isinstance(private["overflow"],Mapping) or any(not isinstance(x,Mapping) or set(x)!={"amount","policy"} or isinstance(x["amount"],bool) or not isinstance(x["amount"],int) or x["amount"]<=0 or x["policy"] not in {"discard","bank"} for x in private["overflow"].values())):return False
 return True
@dataclass(frozen=True,slots=True)
class ProgressionProposal:
 schema:str;proposal_ref:str;operation_ref:str;source_progression_revision:int;kind:ProgressionProposalKind;public_preview:Mapping[str,Any];private_reconciliation:Mapping[str,Any]|None;validation_errors:tuple[str,...];requires_platform_commit:bool=True;commits_state:bool=False
 def __post_init__(self):
  if self.schema!=CHARACTER_PROGRESSION_PROPOSAL_SCHEMA or self.requires_platform_commit is not True or self.commits_state is not False:raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_proposal","authority 无效。")
  _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref")
  if isinstance(self.source_progression_revision,bool) or not isinstance(self.source_progression_revision,int) or self.source_progression_revision<0 or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_proposal","proposal fields invalid")
  if not _proposal_payload_valid(self.kind,self.public_preview,self.private_reconciliation):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_proposal","kind/public/private payload invalid")
  object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public_preview"));object.__setattr__(self,"private_reconciliation",None if self.private_reconciliation is None else freeze_json(self.private_reconciliation,"private"))
@dataclass(frozen=True,slots=True)
class ProgressionResult:
 schema:str;operation_ref:str;request_fingerprint:str;expected_revision:int;source_progression_revision:int;status:ProgressionStatus;proposal:ProgressionProposal|None=None;problems:tuple[Problem,...]=();result_fingerprint:str="sha256:"+"0"*64
 def __post_init__(self):
  if self.schema!=CHARACTER_PROGRESSION_RESULT_SCHEMA or not isinstance(self.problems,tuple) or any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.expected_revision,self.source_progression_revision)):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","result invalid")
  if self.proposal is not None and (self.proposal.operation_ref!=self.operation_ref or self.proposal.source_progression_revision!=self.source_progression_revision):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","proposal identity mismatch")
  if self.status in {ProgressionStatus.PROPOSED,ProgressionStatus.INVALID} and (self.proposal is None or self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","proposal status invalid")
  if self.status is ProgressionStatus.INVALID and self.proposal is not None and self.proposal.kind is not ProgressionProposalKind.VALIDATION:raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","invalid kind mismatch")
  if self.status is ProgressionStatus.PROPOSED and self.proposal is not None and self.proposal.kind is ProgressionProposalKind.VALIDATION:raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","proposed validation mismatch")
  if self.status in {ProgressionStatus.BLOCKED,ProgressionStatus.CANCELLED,ProgressionStatus.TIMED_OUT} and (self.proposal is not None or not self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"progression_result","terminal status invalid")
def progression_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_progression_revision":x.source_progression_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})

def decode_progression_snapshot(value):
 v=freeze_json(value,"progression_snapshot")
 if set(v)!=set(ProgressionSnapshot.__dataclass_fields__) or not all(isinstance(v[n],tuple) for n in ("unlocked_refs","consumed_cause_refs","consumed_dedupe_keys")):raise ValueError("snapshot fields invalid")
 d=dict(v);return ProgressionSnapshot(**d)
def decode_progression_request(value):
 v=freeze_json(value,"progression_request")
 if set(v)!={"schema","envelope","action","snapshot","input"} or not all(isinstance(v[n],Mapping) for n in ("envelope","snapshot","input")):raise ValueError("request fields invalid")
 return ProgressionRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),ProgressionAction(str(v["action"])),decode_progression_snapshot(v["snapshot"]),v["input"])
def decode_progression_result(value):
 v=freeze_json(value,"progression_result")
 if set(v)!=set(ProgressionResult.__dataclass_fields__) or not isinstance(v["problems"],tuple):raise ValueError("result fields invalid")
 p=v["proposal"];proposal=None
 if p is not None:
  if not isinstance(p,Mapping) or set(p)!=set(ProgressionProposal.__dataclass_fields__) or not isinstance(p["validation_errors"],tuple):raise ValueError("proposal fields invalid")
  proposal=ProgressionProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_progression_revision"],ProgressionProposalKind(str(p["kind"])),p["public_preview"],p["private_reconciliation"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["commits_state"])
 problems=[]
 for x in v["problems"]:
  if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__) or not isinstance(x["retryable"],bool):raise ValueError("problem invalid")
  problems.append(Problem(ProblemCode(str(x["code"])),str(x["failed_operation"]),str(x["reason"]),str(x["automatic_handling"]),str(x["next_action"]),x["retryable"]))
 r=ProgressionResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_progression_revision"],ProgressionStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
 if r.result_fingerprint!=progression_result_fingerprint(r):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","result fingerprint mismatch")
 return r

class CharacterProgressionEvaluator:
 def __init__(self,artifact):
  c=artifact.get("character_progression_definitions")
  if not isinstance(c,Mapping) or set(c)!={"schema","definitions","catalog_sha256"} or c.get("schema")!="se-character-progression-catalog-ir/1.0.0" or c.get("catalog_sha256")!=canonical_fingerprint({k:v for k,v in c.items() if k!="catalog_sha256"}):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"progression_catalog","catalog invalid")
  try:
   author={"schema":CHARACTER_PROGRESSION_AUTHOR_SCHEMA,"definitions":[{k:_plain(v) for k,v in d.items() if k not in {"schema","definition_sha256"}} for d in c["definitions"]]}
   rebuilt=compile_character_progression_definitions(author)
  except (CharacterProgressionContractError,KeyError,TypeError):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"progression_catalog","catalog IR contract invalid") from None
  if _plain(c)!=rebuilt:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"progression_catalog","catalog IR is not canonical")
  defs={}
  for d in c["definitions"]:
   if d.get("definition_sha256")!=canonical_fingerprint({k:v for k,v in d.items() if k!="definition_sha256"}) or d["progression_ref"] in defs:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"progression_definition","definition invalid")
   defs[d["progression_ref"]]=freeze_json(d,"definition")
  for e in artifact.get("event_compositions",()):
   b=e.get("character_progression")
   if b is not None and (b.get("progression_ref") not in defs or b.get("definition_sha256")!=defs[b["progression_ref"]]["definition_sha256"]):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"progression_binding","binding invalid")
  self.definitions=MappingProxyType(defs)
 def evaluate(self,r):
  s=r.snapshot
  if r.envelope.request_fingerprint!=progression_request_fingerprint(r) or s.fingerprint!=progression_snapshot_fingerprint(s):return self._blocked(r,ProblemCode.RESULT_STALE,"request/snapshot stale")
  d=self.definitions.get(s.progression_ref)
  if d is None or d["definition_sha256"]!=s.definition_sha256:return self._blocked(r,ProblemCode.CONTRACT_INCOMPATIBLE,"definition mismatch")
  tracks={x["track_ref"]:x for x in d["tracks"]};pools={x["pool_ref"]:x for x in d["point_pools"]};unlocks={x["unlock_ref"]:x for x in d["unlocks"]}
  bank_keys=(set(tracks) if d["overflow_policy"]=="bank" else set())|{key for key,value in pools.items() if value["overflow"]=="bank"}
  existing_unlocks=set(s.unlocked_refs)
  unlock_state_valid=set(existing_unlocks)<=set(unlocks) and all(set(unlocks[item]["requires"])<=existing_unlocks and not(set(unlocks[item]["excludes"])&existing_unlocks) for item in existing_unlocks)
  if unlock_state_valid:
   unlock_state_valid=not any(a in unlocks[b]["excludes"] or b in unlocks[a]["excludes"] for a in existing_unlocks for b in existing_unlocks if a!=b)
  if set(s.track_values)!=set(tracks) or set(s.point_values)!=set(pools) or set(s.bank_values)!=bank_keys or not unlock_state_valid or any(not tracks[k]["starting_value"]<=s.track_values[k]<=tracks[k]["cap"] for k in tracks) or any(s.point_values[k]>pools[k]["cap"] for k in pools) or any(s.bank_values[k]>(tracks[k]["cap"] if k in tracks else pools[k]["cap"]) for k in bank_keys):return self._blocked(r,ProblemCode.RESULT_STALE,"state keys/bounds/unlock closure mismatch")
  expected={ProgressionAction.PREVIEW_GAIN:{"receipt"},ProgressionAction.ADVANCE:{"receipt"},ProgressionAction.SPEND:{"pool_ref","amount"},ProgressionAction.CHOOSE_UNLOCK:{"unlock_ref"},ProgressionAction.DEFER:{"receipt"},ProgressionAction.RESPEC:{"self_confirmed","gate_receipt","respec_plan"}}
  if set(r.input)!=expected[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action input shape invalid")
  public={"model":d["model"],"source_kind":None,"track_count":len(tracks),"unlock_choices":len(unlocks),"defer_allowed":d["defer_allowed"],"respec_available":d["respec_policy"]["allowed"]}
  state_private={"actor_ref":s.actor_ref,"room_ref":s.room_ref,"base_actor_revision":s.actor_revision,"base_room_revision":s.room_revision,"base_progression_revision":s.progression_revision,"consume_cause":False,"platform_commit_required":True}
  if r.action is ProgressionAction.SPEND:
   if d["model"]=="none":return self._blocked(r,ProblemCode.INPUT_INVALID,"none model cannot spend")
   pool=r.input.get("pool_ref");amount=r.input.get("amount")
   if pool not in pools or isinstance(amount,bool) or not isinstance(amount,int) or amount<=0 or amount>s.point_values[pool]:return self._blocked(r,ProblemCode.INPUT_INVALID,"point spend invalid")
   return self._proposal(r,ProgressionProposalKind.PROGRESSION,public,{**state_private,"set_point_values":{**s.point_values,pool:s.point_values[pool]-amount}},())
  if r.action is ProgressionAction.CHOOSE_UNLOCK:
   if d["model"]=="none":return self._blocked(r,ProblemCode.INPUT_INVALID,"none model cannot unlock")
   ur=r.input.get("unlock_ref");u=unlocks.get(ur);existing=set(s.unlocked_refs)
   reverse_excluded=any(ur in unlocks[item]["excludes"] for item in existing)
   if u is None or ur in existing or any(x not in existing for x in u["requires"]) or any(x in existing for x in u["excludes"]) or reverse_excluded or s.point_values[u["pool_ref"]]<u["cost"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"unlock invalid")
   return self._proposal(r,ProgressionProposalKind.UNLOCK,public,{**state_private,"append_unlock_ref":ur,"set_point_values":{**s.point_values,u["pool_ref"]:s.point_values[u["pool_ref"]]-u["cost"]}},())
  if r.action is ProgressionAction.RESPEC:
   if d["model"]=="none":return self._blocked(r,ProblemCode.INPUT_INVALID,"none model cannot respec")
   policy=d["respec_policy"]
   if not policy["allowed"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"respec disabled")
   gate=r.input.get("gate_receipt");gate_fields={"schema","receipt_ref","operation_ref","actor_ref","definition_sha256","progression_revision","respec_plan_sha256","self_confirmed","fingerprint"};plan=r.input.get("respec_plan")
   remove=plan.get("remove_unlock_refs") if isinstance(plan,Mapping) else None;set_tracks=plan.get("set_track_values") if isinstance(plan,Mapping) else None
   remaining=set(s.unlocked_refs)-(set(remove) if isinstance(remove,Sequence) and not isinstance(remove,(str,bytes)) else set())
   closure_ok=all(set(unlocks[item]["requires"])<=remaining and not(set(unlocks[item]["excludes"])&remaining) for item in remaining)
   realloc=policy["track_reallocation"];allowed_tracks=set(realloc["track_refs"]);next_track_values=dict(s.track_values)
   track_plan_valid=isinstance(set_tracks,Mapping) and set(set_tracks)<=allowed_tracks and all(not isinstance(value,bool) and isinstance(value,int) and tracks[key]["starting_value"]<=value<=tracks[key]["cap"] for key,value in set_tracks.items())
   if track_plan_valid:next_track_values.update(set_tracks)
   if not realloc["allowed"]:track_plan_valid=track_plan_valid and not set_tracks
   else:track_plan_valid=track_plan_valid and bool(set_tracks) and sum(next_track_values[key] for key in allowed_tracks)==sum(s.track_values[key] for key in allowed_tracks)
   plan_valid=isinstance(plan,Mapping) and set(plan)=={"remove_unlock_refs","set_track_values"} and isinstance(remove,Sequence) and not isinstance(remove,(str,bytes)) and len(remove)==len(set(remove)) and set(remove)<=set(s.unlocked_refs) and closure_ok and track_plan_valid
   plan_sha256=canonical_fingerprint(_plain(plan)) if isinstance(plan,Mapping) else ""
   gate_valid=isinstance(gate,Mapping) and set(gate)==gate_fields and gate.get("schema")=="platform-progression-respec-gate-receipt/1.0.0" and gate.get("operation_ref")==r.envelope.operation_ref and gate.get("actor_ref")==s.actor_ref and gate.get("definition_sha256")==s.definition_sha256 and gate.get("progression_revision")==s.progression_revision and gate.get("respec_plan_sha256")==plan_sha256 and gate.get("self_confirmed") is True and gate.get("fingerprint")==canonical_fingerprint({k:_plain(v) for k,v in gate.items() if k!="fingerprint"})
   if r.input.get("self_confirmed") is not True or not plan_valid or not gate_valid:return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("respec_confirmation_gate_required",),ProgressionStatus.INVALID)
   refunds={pool:0 for pool in pools}
   for item in remove:refunds[unlocks[item]["pool_ref"]]+=unlocks[item]["cost"]
   if any(s.point_values[pool]+value>pools[pool]["cap"] for pool,value in refunds.items()):return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("respec_refund_overflow",),ProgressionStatus.INVALID)
   return self._proposal(r,ProgressionProposalKind.RESPEC_GATE,public,{**state_private,"respec_candidate":True,"remove_unlock_refs":list(remove),"set_track_values":next_track_values,"derived_refund_points":refunds,"set_point_values":{pool:s.point_values[pool]+refunds[pool] for pool in pools},"self_confirmed":True,"gate_receipt_ref":gate["receipt_ref"],"respec_plan_sha256":plan_sha256,"permanent_change_committed":False},())
  receipt=r.input.get("receipt");fields={"schema","receipt_ref","cause_ref","cause_kind","actor_ref","room_ref","progression_ref","definition_sha256","actor_revision","room_revision","progression_revision","dedupe_key","progression_grants","committed","fingerprint"}
  if not isinstance(receipt,Mapping) or set(receipt)!=fields or receipt.get("schema")!="platform-progression-cause-receipt/1.0.0" or receipt.get("committed") is not True:return self._blocked(r,ProblemCode.INPUT_INVALID,"committed cause receipt required")
  try:
   for name in ("receipt_ref","cause_ref","actor_ref","room_ref","dedupe_key"):_ref(receipt.get(name),name)
   _hash(receipt.get("fingerprint"),"fingerprint")
  except CharacterProgressionContractError:return self._blocked(r,ProblemCode.INPUT_INVALID,"receipt refs/hash invalid")
  material={k:_plain(v) for k,v in receipt.items() if k!="fingerprint"}
  if receipt.get("fingerprint")!=canonical_fingerprint(material) or receipt.get("cause_kind") not in {"reward","milestone","cause"} or receipt.get("actor_ref")!=s.actor_ref or receipt.get("room_ref")!=s.room_ref or receipt.get("progression_ref")!=s.progression_ref or receipt.get("definition_sha256")!=s.definition_sha256 or receipt.get("actor_revision")!=s.actor_revision or receipt.get("room_revision")!=s.room_revision or receipt.get("progression_revision")!=s.progression_revision:return self._blocked(r,ProblemCode.RESULT_STALE,"receipt identity/revision mismatch")
  if receipt.get("cause_ref") in s.consumed_cause_refs or receipt.get("dedupe_key") in s.consumed_dedupe_keys:return self._blocked(r,ProblemCode.RESULT_STALE,"cause/dedupe already consumed")
  grants=receipt.get("progression_grants")
  if not isinstance(grants,Mapping) or any(k not in tracks or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in grants.items()):return self._blocked(r,ProblemCode.INPUT_INVALID,"receipt grants invalid")
  public={**public,"source_kind":receipt["cause_kind"]}
  if d["model"]=="none":
   if r.action not in {ProgressionAction.PREVIEW_GAIN,ProgressionAction.ADVANCE,ProgressionAction.DEFER}:return self._blocked(r,ProblemCode.INPUT_INVALID,"none model does not support spend/unlock/respec")
   if r.action is ProgressionAction.DEFER and not d["defer_allowed"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"defer disabled")
   return self._proposal(r,ProgressionProposalKind.NO_CHANGE,public,{"cause_ref":receipt["cause_ref"],"dedupe_key":receipt["dedupe_key"],"reason":"model_none","consume_cause":r.action is ProgressionAction.ADVANCE,"deferred":r.action is ProgressionAction.DEFER,"platform_commit_required":True},())
  if r.action is ProgressionAction.DEFER:
   if not d["defer_allowed"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"defer disabled")
   return self._proposal(r,ProgressionProposalKind.DEFER,public,{**state_private,"cause_ref":receipt["cause_ref"],"receipt_ref":receipt["receipt_ref"],"dedupe_key":receipt["dedupe_key"],"deferred":True},())
  next_tracks=dict(s.track_values);next_points=dict(s.point_values);next_bank=dict(s.bank_values);crossed=[];overflow={}
  for tr,amount in grants.items():
   old=next_tracks[tr];raw=old+amount;cap=tracks[tr]["cap"]
   if raw>cap:
    policy=d["overflow_policy"];extra=raw-cap
    if policy=="block":return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("track_overflow",),ProgressionStatus.INVALID)
    if policy=="bank":
     if next_bank[tr]+extra>cap:return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("track_bank_overflow",),ProgressionStatus.INVALID)
     next_bank[tr]+=extra
    overflow[tr]={"amount":extra,"policy":policy};raw=cap
   next_tracks[tr]=raw
   for threshold in tracks[tr]["thresholds"]:
    if old<threshold["value"]<=raw:
     crossed.append({"track_ref":tr,"value":threshold["value"]})
     for pool,points in threshold["grant_points"].items():next_points[pool]+=points
  for pool,value in tuple(next_points.items()):
   cap=pools[pool]["cap"]
   if value>cap:
    policy=pools[pool]["overflow"]
    if policy=="block":return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("point_overflow",),ProgressionStatus.INVALID)
    extra=value-cap
    if policy=="bank":
     if next_bank[pool]+extra>cap:return self._proposal(r,ProgressionProposalKind.VALIDATION,public,None,("point_bank_overflow",),ProgressionStatus.INVALID)
     next_bank[pool]+=extra
    overflow[pool]={"amount":extra,"policy":policy};next_points[pool]=cap
  private={**state_private,"cause_ref":receipt["cause_ref"],"receipt_ref":receipt["receipt_ref"],"dedupe_key":receipt["dedupe_key"],"consume_cause":r.action is ProgressionAction.ADVANCE,"set_track_values":next_tracks,"set_point_values":next_points,"set_bank_values":next_bank,"crossed_thresholds":crossed,"overflow":overflow}
  if r.action is ProgressionAction.PREVIEW_GAIN:return self._proposal(r,ProgressionProposalKind.PREVIEW,public,private,())
  if r.action is ProgressionAction.ADVANCE:return self._proposal(r,ProgressionProposalKind.PROGRESSION,public,private,())
  raise AssertionError("unreachable progression action")
 def _proposal(self,r,kind,public,private,errors,status=ProgressionStatus.PROPOSED):
  p=ProgressionProposal(CHARACTER_PROGRESSION_PROPOSAL_SCHEMA,"progression."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.progression_revision,kind,public,private,tuple(errors));x=ProgressionResult(CHARACTER_PROGRESSION_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.progression_revision,status,p);return replace(x,result_fingerprint=progression_result_fingerprint(x))
 def _blocked(self,r,code,reason):
  p=Problem(code,"evaluate character progression",reason,"no state proposal was committed","refresh receipts and revisions") ;x=ProgressionResult(CHARACTER_PROGRESSION_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.progression_revision,ProgressionStatus.BLOCKED,problems=(p,));return replace(x,result_fingerprint=progression_result_fingerprint(x))
class CharacterProgressionService:
 def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
 async def evaluate_character_progression(self,r,bridge):
  c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);d=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,ProgressionStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=d:return self._terminal(r,ProgressionStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  x=self.evaluator.evaluate(r)
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,ProgressionStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=d:return self._terminal(r,ProgressionStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  return x
 def _terminal(self,r,status,code):
  p=Problem(code,"evaluate character progression","cancelled or timed out","no proposal returned","resume with fresh revisions");x=ProgressionResult(CHARACTER_PROGRESSION_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.progression_revision,status,problems=(p,));return replace(x,result_fingerprint=progression_result_fingerprint(x))
class CharacterProgressionStoryEnginePort(Protocol):
 async def evaluate_character_progression(self,request:ProgressionRequest,bridge:PlatformBridge)->ProgressionResult:...
