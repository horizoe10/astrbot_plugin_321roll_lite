"""Committed-cause-bound, proposal-only reward settlement."""
from __future__ import annotations
from collections.abc import Mapping,Sequence
from dataclasses import dataclass,replace
from datetime import UTC,datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any,Protocol
from .contracts.port import CancellationCheck,OperationEnvelope,PlatformBridge,PortContractError,Problem,ProblemCode,canonical_fingerprint,freeze_json

REWARD_SETTLEMENT_CAPABILITY="reward.settlement/1.0.0"
REWARD_SETTLEMENT_AUTHOR_SCHEMA="se-reward-settlement-definitions/1.0.0"
REWARD_SETTLEMENT_SNAPSHOT_SCHEMA="se-reward-settlement-snapshot/1.0.0"
REWARD_SETTLEMENT_REQUEST_SCHEMA="se-reward-settlement-evaluation/1.0.0"
REWARD_SETTLEMENT_PROPOSAL_SCHEMA="se-reward-settlement-proposal/1.0.0"
REWARD_SETTLEMENT_RESULT_SCHEMA="se-reward-settlement-result/1.0.0"
_CAUSE_TYPES=frozenset({"encounter","quest","milestone","exploration","social","crafting","host_award"})
_TARGET_KINDS=frozenset({"currency","progression","inventory","ability"})
class RewardSettlementContractError(ValueError):
 def __init__(self,code,path,reason):self.code,self.path,self.reason=code,path,reason;super().__init__(f"{code}:{path}")
def _fail(c,p,r):raise RewardSettlementContractError(c,p,r)
def _text(v,p,n=240):
 if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("reward.text_invalid",p,"必须是有界非空文本。")
 return v.strip()
def _ref(v,p):
 r=_text(v,p,128)
 if not r[0].isalnum() or any(not(c.isalnum() or c in "_.:@-") for c in r):_fail("reward.ref_invalid",p,"必须是 opaque ref。")
 return r
def _hash(v,p):
 r=_text(v,p,71)
 if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("reward.hash_invalid",p,"必须是 SHA-256。")
 return r
def _map(v,p):
 if not isinstance(v,Mapping):_fail("reward.object_invalid",p,"必须是对象。")
 return v
def _seq(v,p):
 if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("reward.array_invalid",p,"必须是数组。")
 return v
def _plain(v):
 if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
 if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
 return v
def reward_claim_dedupe_material(base_key,scope,reward_ref,definition_sha256,actor_ref=None):return {"schema":"se-reward-claim-dedupe-material/1.0.0","base_key":base_key,"scope":scope,"reward_ref":reward_ref,"definition_sha256":definition_sha256,"actor_ref":actor_ref}
def reward_claim_dedupe_key(base_key,scope,reward_ref,definition_sha256,actor_ref=None):return "dedupe."+canonical_fingerprint(reward_claim_dedupe_material(base_key,scope,reward_ref,definition_sha256,actor_ref))[7:]

def compile_reward_settlement_definitions(document):
 if not isinstance(document,Mapping) or set(document)!={"schema","target_definitions","definitions"} or document.get("schema")!=REWARD_SETTLEMENT_AUTHOR_SCHEMA:_fail("reward.document_invalid","$","作者文档无效。")
 targets={};target_values=[]
 for i,raw in enumerate(_seq(document["target_definitions"],"target_definitions")):
  v=_map(raw,f"target_definitions[{i}]")
  if set(v)!={"target_ref","kind","label","definition_sha256"}:_fail("reward.target_fields_invalid",f"target_definitions[{i}]","target definition 字段无效。")
  ref=_ref(v["target_ref"],"target_ref");kind=v["kind"]
  if ref in targets or kind not in _TARGET_KINDS:_fail("reward.target_invalid","target_definitions","target identity/kind 无效。")
  item={"target_ref":ref,"kind":kind,"label":_text(v["label"],"label"),"definition_sha256":_hash(v["definition_sha256"],"definition_sha256")};targets[ref]=item;target_values.append(item)
 if not targets:_fail("reward.targets_empty","target_definitions","至少一个注册奖励目标。")
 definitions=[];seen=set()
 for i,raw in enumerate(_seq(document["definitions"],"definitions")):
  p=f"definitions[{i}]";v=_map(raw,p)
  if set(v)!={"reward_ref","label","cause_types","cause_refs","eligibility","allocation_mode","entries","choice_groups","claim_policy","dedupe_scope"}:_fail("reward.definition_fields_invalid",p,"definition 字段无效。")
  ref=_ref(v["reward_ref"],p);cause_types=[str(x) for x in _seq(v["cause_types"],p)];cause_refs=[_ref(x,p) for x in _seq(v["cause_refs"],p)]
  if ref in seen or not cause_types or len(cause_types)!=len(set(cause_types)) or any(x not in _CAUSE_TYPES for x in cause_types) or not cause_refs or len(cause_refs)!=len(set(cause_refs)):_fail("reward.definition_invalid",p,"reward identity/cause types/refs 无效。")
  seen.add(ref);elig=_map(v["eligibility"],p)
  if set(elig)!={"mode","minimum","maximum"} or elig["mode"] not in {"actor","party","explicit_roster"} or any(isinstance(elig[x],bool) or not isinstance(elig[x],int) for x in ("minimum","maximum")) or not 1<=elig["minimum"]<=elig["maximum"]<=64:_fail("reward.eligibility_invalid",p,"eligibility 无效。")
  mode=v["allocation_mode"]
  if mode not in {"personal","shared","mixed"}:_fail("reward.allocation_mode_invalid",p,"allocation mode 无效。")
  entries=[];entry_refs=set()
  for j,eraw in enumerate(_seq(v["entries"],p)):
   e=_map(eraw,p)
   if set(e)!={"entry_ref","target_ref","quantity","scope","overflow","choice_group_ref"}:_fail("reward.entry_fields_invalid",p,"entry 字段无效。")
   er=_ref(e["entry_ref"],p);tr=_ref(e["target_ref"],p);q=e["quantity"];scope=e["scope"]
   if er in entry_refs or tr not in targets or isinstance(q,bool) or not isinstance(q,int) or q<=0 or scope not in {"personal","shared"} or e["overflow"] not in {"block","defer","discard"} or e["choice_group_ref"] is not None and not isinstance(e["choice_group_ref"],str):_fail("reward.entry_invalid",p,"entry identity/target/quantity/policy 无效。")
   entry_refs.add(er);entries.append({"entry_ref":er,"target_ref":tr,"target_kind":targets[tr]["kind"],"target_label":targets[tr]["label"],"target_definition_sha256":targets[tr]["definition_sha256"],"quantity":q,"scope":scope,"overflow":e["overflow"],"choice_group_ref":None if e["choice_group_ref"] is None else _ref(e["choice_group_ref"],p)})
  if not entries or mode=="personal" and any(x["scope"]!="personal" for x in entries) or mode=="shared" and any(x["scope"]!="shared" for x in entries):_fail("reward.entries_mode_invalid",p,"entries 与 allocation mode 不一致。")
  groups=[];group_refs=set();grouped=set()
  for graw in _seq(v["choice_groups"],p):
   g=_map(graw,p)
   if set(g)!={"group_ref","label","entry_refs","select_exactly"}:_fail("reward.choice_group_fields_invalid",p,"choice group 字段无效。")
   gr=_ref(g["group_ref"],p);refs=[_ref(x,p) for x in _seq(g["entry_refs"],p)]
   if gr in group_refs or len(refs)<2 or len(refs)!=len(set(refs)) or any(x not in entry_refs for x in refs) or g["select_exactly"]!=1 or grouped&set(refs):_fail("reward.choice_group_invalid",p,"choice group 必须互斥、唯一且 exactly one。")
   group_refs.add(gr);grouped|=set(refs);groups.append({"group_ref":gr,"label":_text(g["label"],p),"entry_refs":refs,"select_exactly":1})
  group_by_entry={entry_ref:g["group_ref"] for g in groups for entry_ref in g["entry_refs"]}
  if any(e["choice_group_ref"] is not None and e["choice_group_ref"] not in group_refs for e in entries) or any(group_by_entry.get(e["entry_ref"])!=e["choice_group_ref"] for e in entries):_fail("reward.choice_binding_invalid",p,"entry choice_group_ref 必须与 group 双向精确一致。")
  policy=_map(v["claim_policy"],p)
  if set(policy)!={"allow_defer","allow_decline","expiry_required"} or not all(isinstance(policy[x],bool) for x in policy):_fail("reward.claim_policy_invalid",p,"claim policy 无效。")
  if v["dedupe_scope"] not in {"cause_reward_actor","cause_reward_party"}:_fail("reward.dedupe_scope_invalid",p,"dedupe scope 无效。")
  material={"schema":"se-reward-settlement-definition-ir/1.0.0","reward_ref":ref,"label":_text(v["label"],p),"cause_types":cause_types,"cause_refs":cause_refs,"eligibility":_plain(elig),"allocation_mode":mode,"entries":entries,"choice_groups":groups,"claim_policy":_plain(policy),"dedupe_scope":v["dedupe_scope"]};material["definition_sha256"]=canonical_fingerprint(material);definitions.append(material)
 catalog={"schema":"se-reward-settlement-catalog-ir/1.0.0","target_definitions":sorted(target_values,key=lambda x:x["target_ref"]),"definitions":sorted(definitions,key=lambda x:x["reward_ref"])};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog
def bind_reward_settlement(extension,catalog):
 if not isinstance(extension,Mapping) or set(extension)!={"reward_ref"}:_fail("reward.extension_invalid","extension","只能包含 reward_ref。")
 ref=_ref(extension["reward_ref"],"reward_ref");d=next((x for x in catalog["definitions"] if x["reward_ref"]==ref),None)
 if d is None:_fail("reward.definition_unknown","reward_ref","reward definition 未注册。")
 return {"schema":"se-reward-settlement-binding-ir/1.0.0","reward_ref":ref,"definition_sha256":d["definition_sha256"]}

class RewardAction(StrEnum):PREVIEW="preview";ALLOCATE="allocate";CHOOSE="choose";CLAIM="claim";DECLINE="decline";DEFER="defer";EXPIRE="expire"
class RewardProposalKind(StrEnum):PREVIEW="preview";ALLOCATION="allocation";CHOICE="choice";CLAIM="claim";DECLINE="decline";DEFER="defer";EXPIRE="expire";VALIDATION="validation"
class RewardStatus(StrEnum):PROPOSED="proposed";INVALID="invalid";BLOCKED="blocked";CANCELLED="cancelled";TIMED_OUT="timed_out"
@dataclass(frozen=True,slots=True)
class RewardSnapshot:
 schema:str;room_ref:str;reward_ref:str;definition_sha256:str;room_revision:int;reward_revision:int;eligible_actor_refs:tuple[str,...];actor_revisions:Mapping[str,int];allocations:Mapping[str,Mapping[str,int]];choices:Mapping[str,Mapping[str,str]];prior_claim_actor_refs:tuple[str,...];declined_actor_refs:tuple[str,...];deferred_actor_refs:tuple[str,...];consumed_dedupe_keys:tuple[str,...];cause_receipt:Mapping[str,Any];expired:bool;expected_session_revision:int;fingerprint:str
 def __post_init__(self):
  if self.schema!=REWARD_SETTLEMENT_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"reward_snapshot","schema invalid")
  for x in (self.room_ref,self.reward_ref):_ref(x,"snapshot.ref")
  _hash(self.definition_sha256,"definition_sha256");_hash(self.fingerprint,"fingerprint")
  if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.room_revision,self.reward_revision,self.expected_session_revision)):raise PortContractError(ProblemCode.INPUT_INVALID,"reward_snapshot","revision invalid")
  for refs in (self.eligible_actor_refs,self.prior_claim_actor_refs,self.declined_actor_refs,self.deferred_actor_refs,self.consumed_dedupe_keys):
   if not isinstance(refs,tuple) or len(refs)!=len(set(refs)):raise PortContractError(ProblemCode.INPUT_INVALID,"reward_snapshot","refs invalid")
   for x in refs:_ref(x,"snapshot.ref")
  if not isinstance(self.actor_revisions,Mapping) or set(self.actor_revisions)!=set(self.eligible_actor_refs) or any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in self.actor_revisions.values()):raise PortContractError(ProblemCode.INPUT_INVALID,"reward_snapshot","actor revisions invalid")
  for m in (self.allocations,self.choices,self.cause_receipt):
   if not isinstance(m,Mapping):raise PortContractError(ProblemCode.INPUT_INVALID,"reward_snapshot","mapping invalid")
  if not isinstance(self.expired,bool):raise PortContractError(ProblemCode.INPUT_INVALID,"reward_snapshot","expired flag invalid")
  object.__setattr__(self,"actor_revisions",freeze_json(self.actor_revisions,"actor_revisions"));object.__setattr__(self,"allocations",freeze_json(self.allocations,"allocations"));object.__setattr__(self,"choices",freeze_json(self.choices,"choices"));object.__setattr__(self,"cause_receipt",freeze_json(self.cause_receipt,"cause_receipt"))
 def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"eligible_actor_refs":list(self.eligible_actor_refs),"actor_revisions":_plain(self.actor_revisions),"allocations":_plain(self.allocations),"choices":_plain(self.choices),"prior_claim_actor_refs":list(self.prior_claim_actor_refs),"declined_actor_refs":list(self.declined_actor_refs),"deferred_actor_refs":list(self.deferred_actor_refs),"consumed_dedupe_keys":list(self.consumed_dedupe_keys),"cause_receipt":_plain(self.cause_receipt)}
 def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def reward_snapshot_fingerprint(x):return canonical_fingerprint(x.material())
@dataclass(frozen=True,slots=True)
class RewardRequest:
 schema:str;envelope:OperationEnvelope;action:RewardAction;snapshot:RewardSnapshot;input:Mapping[str,Any]
 def __post_init__(self):
  if self.schema!=REWARD_SETTLEMENT_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_reward_settlement" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,RewardAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"reward_request","request invalid")
  object.__setattr__(self,"input",freeze_json(self.input,"reward_input"))
def reward_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})
@dataclass(frozen=True,slots=True)
class RewardProposal:
 schema:str;proposal_ref:str;operation_ref:str;source_reward_revision:int;kind:RewardProposalKind;public_preview:Mapping[str,Any];private_reconciliation:Mapping[str,Any]|None;validation_errors:tuple[str,...];requires_platform_commit:bool=True;commits_state:bool=False
 def __post_init__(self):
  if self.schema!=REWARD_SETTLEMENT_PROPOSAL_SCHEMA or self.requires_platform_commit is not True or self.commits_state is not False:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","authority invalid")
  _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref")
  if isinstance(self.source_reward_revision,bool) or not isinstance(self.source_reward_revision,int) or self.source_reward_revision<0 or not isinstance(self.public_preview,Mapping) or set(self.public_preview)!={"reward_label","cause_type","eligible_count","allocation_mode","choice_groups","entries","claim_state","expires"} or not isinstance(self.public_preview.get("reward_label"),str) or self.public_preview.get("cause_type") not in _CAUSE_TYPES or self.public_preview.get("allocation_mode") not in {"personal","shared","mixed"} or self.public_preview.get("claim_state") not in {"open","expired"} or any(isinstance(self.public_preview.get(x),bool) or not isinstance(self.public_preview.get(x),int) or self.public_preview.get(x)<0 for x in ("eligible_count","choice_groups")) or not isinstance(self.public_preview.get("expires"),bool) or not isinstance(self.public_preview.get("entries"),Sequence) or isinstance(self.public_preview.get("entries"),(str,bytes)) or any(not isinstance(x,Mapping) or set(x)!={"label","target_kind","quantity","scope","overflow","choice_group_label"} or x["target_kind"] not in _TARGET_KINDS or isinstance(x["quantity"],bool) or not isinstance(x["quantity"],int) or x["quantity"]<=0 or x["scope"] not in {"personal","shared"} or x["overflow"] not in {"block","defer","discard"} or x["choice_group_label"] is not None and not isinstance(x["choice_group_label"],str) for x in self.public_preview.get("entries",())) or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","public/result fields invalid")
  expected={RewardProposalKind.PREVIEW:{"base_reward_revision","cause_ref","dedupe_key"},RewardProposalKind.ALLOCATION:{"base_reward_revision","entry_ref","set_allocations"},RewardProposalKind.CHOICE:{"base_reward_revision","actor_ref","group_ref","entry_ref","set_choices"},RewardProposalKind.CLAIM:{"base_reward_revision","initiator_actor_ref","actor_revisions","cause_ref","dedupe_key","dedupe_material","atomic_awards","claim_actor_refs","remove_deferred_actor_refs","platform_commit_required"},RewardProposalKind.DECLINE:{"base_reward_revision","actor_ref","append_declined_actor_ref","remove_deferred_actor_refs"},RewardProposalKind.DEFER:{"base_reward_revision","actor_ref","append_deferred_actor_ref"},RewardProposalKind.EXPIRE:{"base_reward_revision","expire_unclaimed_actor_refs","set_expired"}}
  if self.kind is RewardProposalKind.VALIDATION:
   if self.private_reconciliation is not None:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","validation private invalid")
  elif not isinstance(self.private_reconciliation,Mapping) or set(self.private_reconciliation)!=expected[self.kind]:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","private shape invalid")
  if isinstance(self.private_reconciliation,Mapping):
   private=self.private_reconciliation
   for key in set(private)&{"cause_ref","dedupe_key","entry_ref","actor_ref","initiator_actor_ref","group_ref","append_declined_actor_ref","append_deferred_actor_ref"}:
    try:_ref(private[key],key)
    except RewardSettlementContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","private ref invalid") from None
   for key in set(private)&{"base_reward_revision"}:
    if isinstance(private[key],bool) or not isinstance(private[key],int) or private[key]<0:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","private revision invalid")
   if "platform_commit_required" in private and private["platform_commit_required"] is not True:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","platform commit flag invalid")
   if "atomic_awards" in private:
    if not isinstance(private["atomic_awards"],Sequence) or isinstance(private["atomic_awards"],(str,bytes)) or any(not isinstance(x,Mapping) or set(x)!={"actor_ref","entry_ref","target_ref","target_kind","target_definition_sha256","quantity","overflow"} or x["target_kind"] not in _TARGET_KINDS or not isinstance(x["target_definition_sha256"],str) or isinstance(x["quantity"],bool) or not isinstance(x["quantity"],int) or x["quantity"]<=0 or x["overflow"] not in {"block","defer","discard"} for x in private["atomic_awards"]):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","atomic award invalid")
    try:
     for award in private["atomic_awards"]:
      for key in ("actor_ref","entry_ref","target_ref"):_ref(award[key],key)
      _hash(award["target_definition_sha256"],"target_definition_sha256")
    except RewardSettlementContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","atomic award identity invalid") from None
   if "claim_actor_refs" in private:
    refs=private["claim_actor_refs"];revisions=private.get("actor_revisions")
    if not isinstance(refs,Sequence) or isinstance(refs,(str,bytes)) or not refs or len(refs)!=len(set(refs)) or not isinstance(revisions,Mapping) or set(revisions)!=set(refs) or any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in revisions.values()):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","claim actor revisions invalid")
    try:
     for ref in refs:_ref(ref,"claim_actor_ref")
    except RewardSettlementContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","claim actor ref invalid") from None
   if "dedupe_material" in private:
    material=private["dedupe_material"]
    if not isinstance(material,Mapping) or set(material)!={"schema","base_key","scope","reward_ref","definition_sha256","actor_ref"} or material.get("schema")!="se-reward-claim-dedupe-material/1.0.0" or material.get("scope") not in {"cause_reward_actor","cause_reward_party"} or material.get("actor_ref") is None and material.get("scope")!="cause_reward_party" or material.get("actor_ref") is not None and material.get("scope")!="cause_reward_actor" or private.get("dedupe_key")!="dedupe."+canonical_fingerprint(_plain(material))[7:]:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","dedupe material invalid")
    try:_ref(material["base_key"],"base_key");_ref(material["reward_ref"],"reward_ref");_hash(material["definition_sha256"],"definition_sha256");None if material["actor_ref"] is None else _ref(material["actor_ref"],"actor_ref")
    except RewardSettlementContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","dedupe material identity invalid") from None
   if "set_allocations" in private and (not isinstance(private["set_allocations"],Mapping) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in private["set_allocations"].items())):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","allocation patch invalid")
   if "set_choices" in private:
    if not isinstance(private["set_choices"],Mapping) or any(not isinstance(v,Mapping) for v in private["set_choices"].values()):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","choice patch invalid")
    try:
     for actor,values in private["set_choices"].items():
      _ref(actor,"choice.actor_ref")
      for group,entry in values.items():_ref(group,"choice.group_ref");_ref(entry,"choice.entry_ref")
    except RewardSettlementContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","choice patch ref invalid") from None
   if "expire_unclaimed_actor_refs" in private and (not isinstance(private["expire_unclaimed_actor_refs"],Sequence) or isinstance(private["expire_unclaimed_actor_refs"],(str,bytes)) or len(private["expire_unclaimed_actor_refs"])!=len(set(private["expire_unclaimed_actor_refs"]))):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","expiry refs invalid")
   if "remove_deferred_actor_refs" in private and (not isinstance(private["remove_deferred_actor_refs"],Sequence) or isinstance(private["remove_deferred_actor_refs"],(str,bytes)) or len(private["remove_deferred_actor_refs"])!=len(set(private["remove_deferred_actor_refs"]))):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","deferred refs invalid")
   if "set_expired" in private and private["set_expired"] is not True:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_proposal","expiry flag invalid")
  object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public_preview"));object.__setattr__(self,"private_reconciliation",None if self.private_reconciliation is None else freeze_json(self.private_reconciliation,"private"))
@dataclass(frozen=True,slots=True)
class RewardResult:
 schema:str;operation_ref:str;request_fingerprint:str;expected_revision:int;source_reward_revision:int;status:RewardStatus;proposal:RewardProposal|None=None;problems:tuple[Problem,...]=();result_fingerprint:str="sha256:"+"0"*64
 def __post_init__(self):
  if self.schema!=REWARD_SETTLEMENT_RESULT_SCHEMA or not isinstance(self.problems,tuple) or self.proposal is not None and (self.proposal.operation_ref!=self.operation_ref or self.proposal.source_reward_revision!=self.source_reward_revision):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_result","result identity invalid")
  if self.status in {RewardStatus.PROPOSED,RewardStatus.INVALID} and (self.proposal is None or self.problems) or self.status in {RewardStatus.BLOCKED,RewardStatus.CANCELLED,RewardStatus.TIMED_OUT} and (self.proposal is not None or not self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_result","status cross-field invalid")
  if self.status is RewardStatus.INVALID and self.proposal is not None and self.proposal.kind is not RewardProposalKind.VALIDATION or self.status is RewardStatus.PROPOSED and self.proposal is not None and self.proposal.kind is RewardProposalKind.VALIDATION:raise PortContractError(ProblemCode.OUTPUT_INVALID,"reward_result","proposal kind/status invalid")
def reward_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_reward_revision":x.source_reward_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})
def decode_reward_snapshot(v):
 v=freeze_json(v,"reward_snapshot")
 if set(v)!=set(RewardSnapshot.__dataclass_fields__) or not all(isinstance(v[x],tuple) for x in ("eligible_actor_refs","prior_claim_actor_refs","declined_actor_refs","deferred_actor_refs","consumed_dedupe_keys")):raise ValueError("snapshot fields invalid")
 return RewardSnapshot(**dict(v))
def decode_reward_request(v):
 v=freeze_json(v,"reward_request")
 if set(v)!={"schema","envelope","action","snapshot","input"} or not all(isinstance(v[x],Mapping) for x in ("envelope","snapshot","input")):raise ValueError("request fields invalid")
 return RewardRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),RewardAction(str(v["action"])),decode_reward_snapshot(v["snapshot"]),v["input"])
def decode_reward_result(v):
 v=freeze_json(v,"reward_result")
 if set(v)!=set(RewardResult.__dataclass_fields__) or not isinstance(v["problems"],tuple):raise ValueError("result fields invalid")
 p=v["proposal"];proposal=None
 if p is not None:
  if not isinstance(p,Mapping) or set(p)!=set(RewardProposal.__dataclass_fields__) or not isinstance(p["validation_errors"],tuple):raise ValueError("proposal fields invalid")
  proposal=RewardProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_reward_revision"],RewardProposalKind(str(p["kind"])),p["public_preview"],p["private_reconciliation"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["commits_state"])
 problems=[]
 for x in v["problems"]:
  if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__) or not isinstance(x["retryable"],bool) or any(not isinstance(x[k],str) for k in ("code","failed_operation","reason","automatic_handling","next_action")):raise ValueError("problem fields invalid")
  problems.append(Problem(ProblemCode(x["code"]),x["failed_operation"],x["reason"],x["automatic_handling"],x["next_action"],x["retryable"]))
 r=RewardResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_reward_revision"],RewardStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
 if r.result_fingerprint!=reward_result_fingerprint(r):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","result fingerprint mismatch")
 return r

class RewardSettlementEvaluator:
 def __init__(self,artifact):
  c=artifact.get("reward_settlement_definitions")
  if not isinstance(c,Mapping) or set(c)!={"schema","target_definitions","definitions","catalog_sha256"} or c.get("catalog_sha256")!=canonical_fingerprint({k:v for k,v in c.items() if k!="catalog_sha256"}):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"reward_catalog","catalog invalid")
  try:
   definitions=[]
   for d in c["definitions"]:
    author={k:_plain(v) for k,v in d.items() if k not in {"schema","definition_sha256"}}
    author["entries"]=[{k:_plain(v) for k,v in entry.items() if k not in {"target_kind","target_label","target_definition_sha256"}} for entry in d["entries"]];definitions.append(author)
   rebuilt=compile_reward_settlement_definitions({"schema":REWARD_SETTLEMENT_AUTHOR_SCHEMA,"target_definitions":_plain(c["target_definitions"]),"definitions":definitions})
  except RewardSettlementContractError:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"reward_catalog","catalog IR invalid") from None
  if rebuilt!=_plain(c):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"reward_catalog","catalog IR noncanonical")
  self.definitions=MappingProxyType({d["reward_ref"]:freeze_json(d,"reward_definition") for d in c["definitions"]})
  for event in artifact.get("event_compositions",()):
   binding=event.get("reward_settlement")
   if binding is not None and (binding.get("reward_ref") not in self.definitions or binding.get("definition_sha256")!=self.definitions[binding["reward_ref"]]["definition_sha256"]):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"reward_binding","binding invalid")
 def evaluate(self,r,now):
  s=r.snapshot
  if r.envelope.request_fingerprint!=reward_request_fingerprint(r) or s.fingerprint!=reward_snapshot_fingerprint(s):return self._blocked(r,ProblemCode.RESULT_STALE,"request/snapshot stale")
  d=self.definitions.get(s.reward_ref)
  if d is None or d["definition_sha256"]!=s.definition_sha256:return self._blocked(r,ProblemCode.CONTRACT_INCOMPATIBLE,"definition mismatch")
  if s.expired:return self._blocked(r,ProblemCode.RESULT_STALE,"reward already expired")
  eligible=set(s.eligible_actor_refs);entries={x["entry_ref"]:x for x in d["entries"]};groups={x["group_ref"]:x for x in d["choice_groups"]};receipt=s.cause_receipt
  allocations_valid=set(s.allocations)<=set(entries) and all(entries[entry]["scope"]=="shared" and isinstance(values,Mapping) and set(values)<=eligible and all(not isinstance(v,bool) and isinstance(v,int) and v>=0 for v in values.values()) and sum(values.values())==entries[entry]["quantity"] for entry,values in s.allocations.items())
  choices_valid=set(s.choices)<=eligible and all(isinstance(values,Mapping) and set(values)<=set(groups) and all(value in groups[group]["entry_refs"] for group,value in values.items()) for values in s.choices.values())
  if not allocations_valid or not choices_valid:return self._blocked(r,ProblemCode.RESULT_STALE,"allocation/choice snapshot invalid")
  receipt_fields={"schema","receipt_ref","cause_ref","cause_type","room_ref","room_revision","reward_ref","definition_sha256","reward_revision","eligible_actor_refs","dedupe_key","expires_at","committed","fingerprint"}
  try:
   for key in ("receipt_ref","cause_ref","room_ref","reward_ref","dedupe_key"):_ref(receipt.get(key),key)
   _hash(receipt.get("definition_sha256"),"definition_sha256");_hash(receipt.get("fingerprint"),"fingerprint")
  except RewardSettlementContractError:return self._blocked(r,ProblemCode.INPUT_INVALID,"cause receipt refs/hash invalid")
  if set(receipt)!=receipt_fields or receipt.get("schema")!="platform-reward-cause-receipt/1.0.0" or receipt.get("committed") is not True or receipt.get("fingerprint")!=canonical_fingerprint({k:_plain(v) for k,v in receipt.items() if k!="fingerprint"}) or receipt.get("cause_type") not in d["cause_types"] or receipt.get("cause_ref") not in d["cause_refs"] or receipt.get("room_ref")!=s.room_ref or receipt.get("room_revision")!=s.room_revision or receipt.get("reward_ref")!=s.reward_ref or receipt.get("definition_sha256")!=s.definition_sha256 or receipt.get("reward_revision")!=s.reward_revision or list(receipt.get("eligible_actor_refs",()))!=list(s.eligible_actor_refs):return self._blocked(r,ProblemCode.RESULT_STALE,"committed cause receipt identity mismatch")
  state_sets=(set(s.prior_claim_actor_refs),set(s.declined_actor_refs),set(s.deferred_actor_refs))
  if not d["eligibility"]["minimum"]<=len(eligible)<=d["eligibility"]["maximum"] or set(s.actor_revisions)!=eligible or not set().union(*state_sets)<=eligible or any(state_sets[i]&state_sets[j] for i in range(3) for j in range(i+1,3)):return self._blocked(r,ProblemCode.RESULT_STALE,"eligibility/claim state invalid")
  try:expires=datetime.fromisoformat(receipt["expires_at"].replace("Z","+00:00")) if receipt["expires_at"] is not None else None
  except (AttributeError,ValueError):return self._blocked(r,ProblemCode.INPUT_INVALID,"expiry invalid")
  if expires is not None and expires.tzinfo is None:return self._blocked(r,ProblemCode.INPUT_INVALID,"expiry timezone required")
  if d["claim_policy"]["expiry_required"] and expires is None:return self._blocked(r,ProblemCode.INPUT_INVALID,"expiry required")
  shapes={RewardAction.PREVIEW:set(),RewardAction.ALLOCATE:{"entry_ref","allocations"},RewardAction.CHOOSE:{"actor_ref","group_ref","entry_ref"},RewardAction.CLAIM:{"actor_ref"},RewardAction.DECLINE:{"actor_ref"},RewardAction.DEFER:{"actor_ref"},RewardAction.EXPIRE:set()}
  if set(r.input)!=shapes[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action input shape invalid")
  public={"reward_label":d["label"],"cause_type":receipt["cause_type"],"eligible_count":len(eligible),"allocation_mode":d["allocation_mode"],"choice_groups":len(groups),"entries":[{"label":e["target_label"],"target_kind":e["target_kind"],"quantity":e["quantity"],"scope":e["scope"],"overflow":e["overflow"],"choice_group_label":None if e["choice_group_ref"] is None else groups[e["choice_group_ref"]]["label"]} for e in entries.values()],"claim_state":"open","expires":expires is not None}
  party_dedupe_key=reward_claim_dedupe_key(receipt["dedupe_key"],"cause_reward_party",s.reward_ref,s.definition_sha256)
  if d["dedupe_scope"]=="cause_reward_party" and party_dedupe_key in s.consumed_dedupe_keys:return self._blocked(r,ProblemCode.RESULT_STALE,"party reward already consumed")
  if r.action is not RewardAction.EXPIRE and expires is not None and now>=expires:return self._blocked(r,ProblemCode.RESULT_STALE,"reward expired")
  if r.action is RewardAction.PREVIEW:return self._proposal(r,RewardProposalKind.PREVIEW,public,{"base_reward_revision":s.reward_revision,"cause_ref":receipt["cause_ref"],"dedupe_key":receipt["dedupe_key"]})
  if r.action is RewardAction.ALLOCATE:
   er=r.input.get("entry_ref");allocation=r.input.get("allocations");entry=entries.get(er)
   if s.prior_claim_actor_refs or s.declined_actor_refs:return self._blocked(r,ProblemCode.RESULT_STALE,"allocation frozen after settlement")
   if entry is None or entry["scope"]!="shared" or not isinstance(allocation,Mapping) or not allocation or set(allocation)-eligible or any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in allocation.values()) or sum(allocation.values())!=entry["quantity"]:return self._invalid(r,public,"shared_allocation_invalid")
   if _plain(s.allocations.get(er,{}))==_plain(allocation):return self._blocked(r,ProblemCode.RESULT_STALE,"allocation already current")
   return self._proposal(r,RewardProposalKind.ALLOCATION,public,{"base_reward_revision":s.reward_revision,"entry_ref":er,"set_allocations":_plain(allocation)})
  if r.action is RewardAction.EXPIRE:
   if expires is None or now<expires:return self._blocked(r,ProblemCode.INPUT_INVALID,"not expired")
   unclaimed=sorted(eligible-set(s.prior_claim_actor_refs)-set(s.declined_actor_refs));return self._proposal(r,RewardProposalKind.EXPIRE,{**public,"claim_state":"expired"},{"base_reward_revision":s.reward_revision,"expire_unclaimed_actor_refs":unclaimed,"set_expired":True})
  actor=r.input.get("actor_ref")
  if actor not in eligible:return self._blocked(r,ProblemCode.INPUT_INVALID,"actor not eligible")
  if r.action is RewardAction.CHOOSE:
   gr=r.input.get("group_ref");er=r.input.get("entry_ref");group=groups.get(gr)
   if actor in set(s.prior_claim_actor_refs)|set(s.declined_actor_refs):return self._blocked(r,ProblemCode.RESULT_STALE,"choice frozen after settlement")
   if group is None or er not in group["entry_refs"]:return self._invalid(r,public,"choice_invalid")
   if s.choices.get(actor,{}).get(gr)==er:return self._blocked(r,ProblemCode.RESULT_STALE,"choice already current")
   choices=_plain(s.choices);choices.setdefault(actor,{})[gr]=er;return self._proposal(r,RewardProposalKind.CHOICE,public,{"base_reward_revision":s.reward_revision,"actor_ref":actor,"group_ref":gr,"entry_ref":er,"set_choices":choices})
  if r.action is RewardAction.DECLINE:
   if not d["claim_policy"]["allow_decline"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"decline disabled")
   if actor in set(s.declined_actor_refs)|set(s.prior_claim_actor_refs):return self._blocked(r,ProblemCode.RESULT_STALE,"decline already settled")
   return self._proposal(r,RewardProposalKind.DECLINE,public,{"base_reward_revision":s.reward_revision,"actor_ref":actor,"append_declined_actor_ref":actor,"remove_deferred_actor_refs":[actor] if actor in s.deferred_actor_refs else []})
  if r.action is RewardAction.DEFER:
   if not d["claim_policy"]["allow_defer"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"defer disabled")
   if actor in set(s.deferred_actor_refs)|set(s.prior_claim_actor_refs)|set(s.declined_actor_refs):return self._blocked(r,ProblemCode.RESULT_STALE,"defer already settled")
   return self._proposal(r,RewardProposalKind.DEFER,public,{"base_reward_revision":s.reward_revision,"actor_ref":actor,"append_deferred_actor_ref":actor})
  if r.action is RewardAction.CLAIM:
   claim_actors=sorted(eligible) if d["dedupe_scope"]=="cause_reward_party" else [actor]
   dedupe_material=reward_claim_dedupe_material(receipt["dedupe_key"],d["dedupe_scope"],s.reward_ref,s.definition_sha256,None if d["dedupe_scope"]=="cause_reward_party" else actor);claim_dedupe_key="dedupe."+canonical_fingerprint(dedupe_material)[7:]
   if claim_dedupe_key in s.consumed_dedupe_keys:return self._blocked(r,ProblemCode.RESULT_STALE,"claim dedupe already consumed")
   if set(claim_actors)&(set(s.prior_claim_actor_refs)|set(s.declined_actor_refs)):return self._blocked(r,ProblemCode.RESULT_STALE,"claim duplicate/declined")
   awards=[]
   for claim_actor in claim_actors:
    actor_choices=s.choices.get(claim_actor,{})
    if set(actor_choices)!=set(groups) or any(actor_choices[g] not in groups[g]["entry_refs"] for g in groups):return self._invalid(r,public,"choice_required")
    for e in entries.values():
     if e["choice_group_ref"] is not None and actor_choices[e["choice_group_ref"]]!=e["entry_ref"]:continue
     quantity=e["quantity"] if e["scope"]=="personal" else s.allocations.get(e["entry_ref"],{}).get(claim_actor,0)
     if e["scope"]=="shared" and (e["entry_ref"] not in s.allocations or sum(s.allocations[e["entry_ref"]].values())!=e["quantity"]):return self._invalid(r,public,"shared_allocation_required")
     if quantity:awards.append({"actor_ref":claim_actor,"entry_ref":e["entry_ref"],"target_ref":e["target_ref"],"target_kind":e["target_kind"],"target_definition_sha256":e["target_definition_sha256"],"quantity":quantity,"overflow":e["overflow"]})
   return self._proposal(r,RewardProposalKind.CLAIM,public,{"base_reward_revision":s.reward_revision,"initiator_actor_ref":actor,"actor_revisions":{x:s.actor_revisions[x] for x in claim_actors},"cause_ref":receipt["cause_ref"],"dedupe_key":claim_dedupe_key,"dedupe_material":dedupe_material,"atomic_awards":awards,"claim_actor_refs":claim_actors,"remove_deferred_actor_refs":[x for x in claim_actors if x in s.deferred_actor_refs],"platform_commit_required":True})
  raise AssertionError("unreachable reward action")
 def _proposal(self,r,kind,public,private,status=RewardStatus.PROPOSED,errors=()):
  p=RewardProposal(REWARD_SETTLEMENT_PROPOSAL_SCHEMA,"reward."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.reward_revision,kind,public,private,tuple(errors));x=RewardResult(REWARD_SETTLEMENT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.reward_revision,status,p);return replace(x,result_fingerprint=reward_result_fingerprint(x))
 def _invalid(self,r,public,error):return self._proposal(r,RewardProposalKind.VALIDATION,public,None,RewardStatus.INVALID,(error,))
 def _blocked(self,r,code,reason):
  p=Problem(code,"evaluate reward settlement",reason,"no reward proposal was committed","refresh cause receipt and reward state");x=RewardResult(REWARD_SETTLEMENT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.reward_revision,RewardStatus.BLOCKED,problems=(p,));return replace(x,result_fingerprint=reward_result_fingerprint(x))
class RewardSettlementService:
 def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
 async def evaluate_reward_settlement(self,r,bridge):
  c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);deadline=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,RewardStatus.CANCELLED,ProblemCode.CANCELLED)
  now=self.clock()
  if now>=deadline:return self._terminal(r,RewardStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  x=self.evaluator.evaluate(r,now)
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,RewardStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,RewardStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  return x
 def _terminal(self,r,status,code):
  p=Problem(code,"evaluate reward settlement","operation cancelled or deadline exceeded","no proposal returned","retry with fresh snapshot");x=RewardResult(REWARD_SETTLEMENT_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.reward_revision,status,problems=(p,));return replace(x,result_fingerprint=reward_result_fingerprint(x))
class RewardSettlementStoryEnginePort(Protocol):
 async def evaluate_reward_settlement(self,request:RewardRequest,bridge:PlatformBridge)->RewardResult:...
