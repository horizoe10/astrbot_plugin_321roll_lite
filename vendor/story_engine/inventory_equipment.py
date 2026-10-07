"""Artifact-bound, proposal-only inventory and equipment semantics."""
from __future__ import annotations
from collections.abc import Mapping,Sequence
from dataclasses import dataclass,replace
from datetime import UTC,datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any,Protocol
from .contracts.port import CancellationCheck,OperationEnvelope,PlatformBridge,PortContractError,Problem,ProblemCode,canonical_fingerprint,freeze_json

INVENTORY_EQUIPMENT_CAPABILITY="inventory.equipment/1.0.0";INVENTORY_AUTHOR_SCHEMA="se-inventory-equipment-definitions/1.0.0";INVENTORY_SNAPSHOT_SCHEMA="se-inventory-equipment-snapshot/1.0.0";INVENTORY_REQUEST_SCHEMA="se-inventory-equipment-evaluation/1.0.0";INVENTORY_PROPOSAL_SCHEMA="se-inventory-equipment-proposal/1.0.0";INVENTORY_RESULT_SCHEMA="se-inventory-equipment-result/1.0.0"
_KINDS=frozenset({"armor","crafted","gear","material","story_item","weapon"});_SLOTS=frozenset({"body","main_hand","utility","none"});_ACTIONS=frozenset({"inspect","transfer","split","merge","equip","unequip","use","consume","drop","repair"})
class InventoryEquipmentContractError(ValueError):
 def __init__(self,c,p,r):self.code,self.path,self.reason=c,p,r;super().__init__(f"{c}:{p}")
def _fail(c,p,r):raise InventoryEquipmentContractError(c,p,r)
def _text(v,p,n=512):
 if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("inventory.text_invalid",p,"bounded text required")
 return v.strip()
def _ref(v,p):
 r=_text(v,p,128)
 if not r[0].isalnum() or any(not(c.isalnum() or c in "_.:@-") for c in r):_fail("inventory.ref_invalid",p,"opaque ref required")
 return r
def _hash(v,p):
 r=_text(v,p,71)
 if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("inventory.hash_invalid",p,"sha256 required")
 return r
def _seq(v,p):
 if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("inventory.array_invalid",p,"array required")
 return v
def _map(v,p):
 if not isinstance(v,Mapping):_fail("inventory.object_invalid",p,"object required")
 return v
def _plain(v):
 if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
 if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
 return v
def compile_inventory_equipment_definitions(doc):
 extended=isinstance(doc,Mapping) and doc.get('schema')=='se-inventory-equipment-definitions/1.1.0'
 fields={"schema","source_authority","equipment_slots","policies","definitions"}|({'instance_attributes'} if extended else set())
 if not isinstance(doc,Mapping) or set(doc)!=fields or doc.get("schema") not in {INVENTORY_AUTHOR_SCHEMA,'se-inventory-equipment-definitions/1.1.0'}:_fail("inventory.document_invalid","$","document invalid")
 source=_map(doc["source_authority"],"source_authority")
 if set(source)!={"path","digest_algorithm","digest"} or source["digest_algorithm"]!="canonical-json-utf8-v1":_fail("inventory.source_invalid","source_authority","source binding invalid")
 _hash(source["digest"],"source_authority.digest");_text(source["path"],"source_authority.path",240)
 slots=[_ref(x,"equipment_slots") for x in _seq(doc["equipment_slots"],"equipment_slots")]
 if set(slots)!={"body","main_hand","utility"}:_fail("inventory.slots_invalid","equipment_slots","exact slots required")
 policies=_map(doc["policies"],"policies")
 if set(policies)!={"containers_available","capacity_available","repair_available","consume_available"} or not all(isinstance(v,bool) for v in policies.values()):_fail("inventory.policies_invalid","policies","policy booleans required")
 if any(policies.values()):_fail("inventory.policy_unsupported","policies","container/capacity/repair/consume are unavailable in 1.0.0")
 out=[];seen=set()
 for i,raw in enumerate(_seq(doc["definitions"],"definitions")):
  p=f"definitions[{i}]";v=_map(raw,p)
  fields={"item_ref","label","description","kind","category","slot","stack_policy","binding_policy","visibility","instance_template","use_effects"}
  if set(v)!=fields:_fail("inventory.definition_fields_invalid",p,"fields invalid")
  ref=_ref(v["item_ref"],p);kind=v["kind"];slot=v["slot"]
  if ref in seen or kind not in _KINDS or slot not in _SLOTS or v["stack_policy"] not in {"unique","stackable"} or v["binding_policy"] not in {"unbound","character_bound","scenario_defined"} or v["visibility"] not in {"public","owner","party","dm"}:_fail("inventory.definition_invalid",p,"identity/policy invalid")
  if (kind=="material")!=(v["stack_policy"]=="stackable"):_fail("inventory.stack_kind_invalid",p,"only material is stackable")
  template=_map(v["instance_template"],p)
  if set(template)!={"quantity_min","quantity_max","durability_mode","durability_max","repair_available","consume_available"}:_fail("inventory.template_fields_invalid",p,"template fields invalid")
  qmin,qmax=template["quantity_min"],template["quantity_max"];dmax=template["durability_max"]
  if isinstance(qmin,bool) or not isinstance(qmin,int) or qmin!=1 or qmax is not None and (isinstance(qmax,bool) or not isinstance(qmax,int) or qmax<qmin) or v["stack_policy"]=="unique" and qmax!=1 or v["stack_policy"]=="stackable" and qmax is not None or template["durability_mode"] not in {"not_applicable","tracked","scenario_defined"} or dmax is not None and (isinstance(dmax,bool) or not isinstance(dmax,int) or dmax<=0) or dmax is not None and template["durability_mode"]!="tracked" or template["repair_available"] is not policies["repair_available"] or template["consume_available"] is not policies["consume_available"]:_fail("inventory.template_invalid",p,"quantity/durability template invalid")
  effects=[]
  for effect in _seq(v["use_effects"],p):
   e=_map(effect,p)
   if set(e)!={"kind","target_kinds","effect","failure_effect","durability_cost"} or e["kind"] not in {"aid","guard","interact","maneuver","parley"} or not e["target_kinds"] or any(x not in {"actor","objective","zone"} for x in e["target_kinds"]) or e["durability_cost"]!=1 or dmax is None:_fail("inventory.use_effect_invalid",p,"use effect invalid")
   effects.append({"kind":e["kind"],"target_kinds":list(e["target_kinds"]),"effect":_text(e["effect"],p),"failure_effect":_text(e["failure_effect"],p),"durability_cost":1})
  seen.add(ref);item={"schema":"se-inventory-equipment-definition-ir/1.0.0","item_ref":ref,"label":_text(v["label"],p),"description":_text(v["description"],p),"kind":kind,"category":_text(v["category"],p),"slot":slot,"stack_policy":v["stack_policy"],"binding_policy":v["binding_policy"],"visibility":v["visibility"],"instance_template":_plain(template),"use_effects":effects};item["definition_sha256"]=canonical_fingerprint(item);out.append(item)
 catalog={"schema":"se-inventory-equipment-catalog-ir/1.0.0","source_authority":_plain(source),"equipment_slots":sorted(slots),"policies":_plain(policies),"definitions":sorted(out,key=lambda x:x["item_ref"])}
 if extended:
  attributes=_map(doc['instance_attributes'],'instance_attributes')
  definitions={item['item_ref']:item for item in out}
  for ref,values in attributes.items():
   if ref not in definitions or not isinstance(values,Mapping) or set(values)!={'carrying_units','charge_max'}:_fail('inventory.instance_attributes_invalid',str(ref),'known item and exact carrying/charge attributes required')
   units,charges=values['carrying_units'],values['charge_max']
   if type(units) is not int or not 1<=units<=100 or charges is not None and (type(charges) is not int or not 1<=charges<=100 or definitions[ref]['stack_policy']!='unique'):_fail('inventory.instance_attributes_invalid',ref,'bounded carrying units and unique item charges required')
  catalog.update(schema='se-inventory-equipment-catalog-ir/1.1.0',instance_attributes=_plain(attributes))
 catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog
def bind_inventory_equipment(extension,catalog):
 if not isinstance(extension,Mapping) or set(extension)!={"item_refs"}:_fail("inventory.extension_invalid","extension","item_refs only")
 refs=[_ref(x,"item_refs") for x in _seq(extension["item_refs"],"item_refs")];defs={x["item_ref"]:x for x in catalog["definitions"]}
 if not refs or len(refs)!=len(set(refs)) or any(x not in defs for x in refs):_fail("inventory.definition_unknown","item_refs","unknown item")
 return {"schema":"se-inventory-equipment-binding-ir/1.0.0","items":[{"item_ref":x,"definition_sha256":defs[x]["definition_sha256"]} for x in refs]}

class InventoryAction(StrEnum):INSPECT="inspect";TRANSFER="transfer";SPLIT="split";MERGE="merge";EQUIP="equip";UNEQUIP="unequip";USE="use";CONSUME="consume";DROP="drop";REPAIR="repair"
class InventoryStatus(StrEnum):PROPOSED="proposed";INVALID="invalid";BLOCKED="blocked";CANCELLED="cancelled";TIMED_OUT="timed_out"
class InventoryProposalKind(StrEnum):INSPECT="inspect";MUTATION="mutation";EFFECT="effect";VALIDATION="validation"
@dataclass(frozen=True,slots=True)
class InventorySnapshot:
 schema:str;room_ref:str;actor_ref:str;owner_ref:str;inventory_ref:str;room_revision:int;actor_revision:int;inventory_revision:int;instances:Mapping[str,Mapping[str,Any]];equipment:Mapping[str,str|None];permissions:Mapping[str,bool];permission_receipt:Mapping[str,Any];cause_receipts:tuple[Mapping[str,Any],...];consumed_dedupe_keys:tuple[str,...];expected_session_revision:int;fingerprint:str
 def __post_init__(self):
  if self.schema!=INVENTORY_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"inventory_snapshot","schema invalid")
  for x in (self.room_ref,self.actor_ref,self.owner_ref,self.inventory_ref):_ref(x,"snapshot.ref")
  if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.room_revision,self.actor_revision,self.inventory_revision,self.expected_session_revision)):raise PortContractError(ProblemCode.INPUT_INVALID,"inventory_snapshot","revision invalid")
  if not all(isinstance(x,Mapping) for x in (self.instances,self.equipment,self.permissions,self.permission_receipt)) or not isinstance(self.cause_receipts,tuple) or not isinstance(self.consumed_dedupe_keys,tuple):raise PortContractError(ProblemCode.INPUT_INVALID,"inventory_snapshot","state invalid")
  if len(self.consumed_dedupe_keys)!=len(set(self.consumed_dedupe_keys)):raise PortContractError(ProblemCode.INPUT_INVALID,"inventory_snapshot","dedupe keys invalid")
  _hash(self.fingerprint,"fingerprint");object.__setattr__(self,"instances",freeze_json(self.instances,"instances"));object.__setattr__(self,"equipment",freeze_json(self.equipment,"equipment"));object.__setattr__(self,"permissions",freeze_json(self.permissions,"permissions"));object.__setattr__(self,"permission_receipt",freeze_json(self.permission_receipt,"permission_receipt"));object.__setattr__(self,"cause_receipts",freeze_json(self.cause_receipts,"cause_receipts"))
 def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"instances":_plain(self.instances),"equipment":_plain(self.equipment),"permissions":_plain(self.permissions),"permission_receipt":_plain(self.permission_receipt),"cause_receipts":_plain(self.cause_receipts),"consumed_dedupe_keys":list(self.consumed_dedupe_keys)}
 def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def inventory_snapshot_fingerprint(x):return canonical_fingerprint(x.material())
@dataclass(frozen=True,slots=True)
class InventoryRequest:
 schema:str;envelope:OperationEnvelope;action:InventoryAction;snapshot:InventorySnapshot;input:Mapping[str,Any]
 def __post_init__(self):
  if self.schema!=INVENTORY_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_inventory_equipment" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,InventoryAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"inventory_request","request invalid")
  object.__setattr__(self,"input",freeze_json(self.input,"inventory_input"))
def inventory_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})
@dataclass(frozen=True,slots=True)
class InventoryProposal:
 schema:str;proposal_ref:str;operation_ref:str;source_inventory_revision:int;kind:InventoryProposalKind;public_preview:Mapping[str,Any];private_reconciliation:Mapping[str,Any]|None;validation_errors:tuple[str,...];requires_platform_commit:bool=True;commits_state:bool=False
 def __post_init__(self):
  if self.schema!=INVENTORY_PROPOSAL_SCHEMA or self.requires_platform_commit is not True or self.commits_state is not False or not isinstance(self.public_preview,Mapping) or set(self.public_preview)!={"item_label","action","availability","quantity","durability","slot","visibility"} or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","proposal invalid")
  _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref")
  base={"base_inventory_revision","instance_ref","item_ref","definition_sha256","owner_ref","platform_commit_required"};private=self.private_reconciliation
  if self.kind is InventoryProposalKind.VALIDATION:
   if private is not None:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","validation private invalid")
  elif not isinstance(private,Mapping):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","private invalid")
  elif self.kind is InventoryProposalKind.INSPECT and set(private)!=base|{"read_only"}:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","inspect private invalid")
  elif self.kind is InventoryProposalKind.EFFECT and set(private)!=base|{"operation","effect","target_ref","target_kind","set_durability","atomic_effect_and_cost"}:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","effect private invalid")
  elif self.kind is InventoryProposalKind.MUTATION:
   allowed={"transfer":base|{"operation","target_owner_ref","preserve_instance_ref"},"split":base|{"operation","split_quantity","new_instance_ref"},"merge":base|{"operation","target_instance_ref","source_quantity","target_quantity","merged_quantity","remove_source_after_commit"},"equip":base|{"operation","slot","expected_slot_instance_ref"},"unequip":base|{"operation","slot"},"drop":base|{"operation","quantity","physical_visibility_preserved"}}
   if private.get("operation") not in allowed or set(private)!=allowed[private["operation"]]:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","mutation private invalid")
  if isinstance(private,Mapping):
   try:
    for key in ("instance_ref","item_ref","owner_ref"):_ref(private[key],key)
    _hash(private["definition_sha256"],"definition_sha256")
   except InventoryEquipmentContractError:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","private identity invalid") from None
   if isinstance(private["base_inventory_revision"],bool) or not isinstance(private["base_inventory_revision"],int) or private["base_inventory_revision"]<0 or private["platform_commit_required"] is not True:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","private authority invalid")
   operation=private.get("operation")
   if operation=="transfer" and (not isinstance(private["target_owner_ref"],str) or private["preserve_instance_ref"] is not True) or operation=="split" and (isinstance(private["split_quantity"],bool) or not isinstance(private["split_quantity"],int) or private["split_quantity"]<=0 or private["new_instance_ref"] is not None) or operation=="merge" and (not isinstance(private["target_instance_ref"],str) or isinstance(private["merged_quantity"],bool) or not isinstance(private["merged_quantity"],int) or private["merged_quantity"]<=0 or private["remove_source_after_commit"] is not True) or operation=="equip" and (private["slot"] not in {"body","main_hand","utility"} or private["expected_slot_instance_ref"] is not None and not isinstance(private["expected_slot_instance_ref"],str)) or operation=="unequip" and private["slot"] not in {"body","main_hand","utility"} or operation=="drop" and (isinstance(private["quantity"],bool) or not isinstance(private["quantity"],int) or private["quantity"]<=0 or private["physical_visibility_preserved"] is not True):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","operation payload invalid")
   if operation=="merge" and (any(isinstance(private[k],bool) or not isinstance(private[k],int) or private[k]<=0 for k in ("source_quantity","target_quantity","merged_quantity")) or private["merged_quantity"]!=private["source_quantity"]+private["target_quantity"]):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","merge quantities invalid")
   if self.kind is InventoryProposalKind.INSPECT and private["read_only"] is not True:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","inspect flag invalid")
   if self.kind is InventoryProposalKind.EFFECT and (private["operation"]!="use" or private["target_kind"] not in {"actor","objective","zone"} or isinstance(private["set_durability"],bool) or not isinstance(private["set_durability"],int) or private["set_durability"]<0 or private["atomic_effect_and_cost"] is not True):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_proposal","effect payload invalid")
  object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public"));object.__setattr__(self,"private_reconciliation",None if self.private_reconciliation is None else freeze_json(self.private_reconciliation,"private"))
@dataclass(frozen=True,slots=True)
class InventoryResult:
 schema:str;operation_ref:str;request_fingerprint:str;expected_revision:int;source_inventory_revision:int;status:InventoryStatus;proposal:InventoryProposal|None=None;problems:tuple[Problem,...]=();result_fingerprint:str="sha256:"+"0"*64
 def __post_init__(self):
  if self.schema!=INVENTORY_RESULT_SCHEMA or not isinstance(self.problems,tuple) or self.proposal is not None and (self.proposal.operation_ref!=self.operation_ref or self.proposal.source_inventory_revision!=self.source_inventory_revision):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_result","identity invalid")
  if self.status in {InventoryStatus.PROPOSED,InventoryStatus.INVALID} and (self.proposal is None or self.problems) or self.status in {InventoryStatus.BLOCKED,InventoryStatus.CANCELLED,InventoryStatus.TIMED_OUT} and (self.proposal is not None or not self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_result","status invalid")
  if self.status is InventoryStatus.INVALID and self.proposal is not None and self.proposal.kind is not InventoryProposalKind.VALIDATION or self.status is InventoryStatus.PROPOSED and self.proposal is not None and self.proposal.kind is InventoryProposalKind.VALIDATION:raise PortContractError(ProblemCode.OUTPUT_INVALID,"inventory_result","kind/status invalid")
def inventory_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_inventory_revision":x.source_inventory_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})
def decode_inventory_snapshot(v):
 v=freeze_json(v,"inventory_snapshot")
 if set(v)!=set(InventorySnapshot.__dataclass_fields__) or not isinstance(v["cause_receipts"],tuple) or not isinstance(v["consumed_dedupe_keys"],tuple):raise ValueError("snapshot fields invalid")
 return InventorySnapshot(**dict(v))
def decode_inventory_request(v):
 v=freeze_json(v,"inventory_request")
 if set(v)!={"schema","envelope","action","snapshot","input"} or not all(isinstance(v[x],Mapping) for x in ("envelope","snapshot","input")):raise ValueError("request fields invalid")
 return InventoryRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),InventoryAction(str(v["action"])),decode_inventory_snapshot(v["snapshot"]),v["input"])
def decode_inventory_result(v):
 v=freeze_json(v,"inventory_result")
 if set(v)!=set(InventoryResult.__dataclass_fields__) or not isinstance(v["problems"],tuple):raise ValueError("result fields invalid")
 p=v["proposal"];proposal=None
 if p is not None:
  if not isinstance(p,Mapping) or set(p)!=set(InventoryProposal.__dataclass_fields__) or not isinstance(p["validation_errors"],tuple):raise ValueError("proposal invalid")
  proposal=InventoryProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_inventory_revision"],InventoryProposalKind(str(p["kind"])),p["public_preview"],p["private_reconciliation"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["commits_state"])
 problems=[]
 for x in v["problems"]:
  if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__) or not isinstance(x["retryable"],bool) or any(not isinstance(x[k],str) for k in ("code","failed_operation","reason","automatic_handling","next_action")):raise ValueError("problem invalid")
  problems.append(Problem(ProblemCode(x["code"]),x["failed_operation"],x["reason"],x["automatic_handling"],x["next_action"],x["retryable"]))
 r=InventoryResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_inventory_revision"],InventoryStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
 if r.result_fingerprint!=inventory_result_fingerprint(r):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","mismatch")
 return r

class InventoryEquipmentEvaluator:
 def __init__(self,artifact):
  c=artifact.get("inventory_equipment_definitions")
  extended=isinstance(c,Mapping) and c.get('schema')=='se-inventory-equipment-catalog-ir/1.1.0'
  fields={"schema","source_authority","equipment_slots","policies","definitions","catalog_sha256"}|({'instance_attributes'} if extended else set())
  if not isinstance(c,Mapping) or set(c)!=fields or c.get("catalog_sha256")!=canonical_fingerprint({k:v for k,v in c.items() if k!="catalog_sha256"}):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"inventory_catalog","catalog invalid")
  try:rebuilt=compile_inventory_equipment_definitions({"schema":'se-inventory-equipment-definitions/1.1.0' if extended else INVENTORY_AUTHOR_SCHEMA,"source_authority":_plain(c["source_authority"]),"equipment_slots":_plain(c["equipment_slots"]),"policies":_plain(c["policies"]),"definitions":[{k:_plain(v) for k,v in x.items() if k not in {"schema","definition_sha256"}} for x in c["definitions"]],**({'instance_attributes':_plain(c['instance_attributes'])} if extended else {})})
  except InventoryEquipmentContractError:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"inventory_catalog","IR semantic invalid") from None
  if rebuilt!=_plain(c):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"inventory_catalog","IR noncanonical")
  self.definitions=MappingProxyType({x["item_ref"]:freeze_json(x,"item") for x in c["definitions"]});self.policies=freeze_json(c["policies"],"policies")
 def evaluate(self,r):
  s=r.snapshot
  if r.envelope.request_fingerprint!=inventory_request_fingerprint(r) or s.fingerprint!=inventory_snapshot_fingerprint(s):return self._blocked(r,ProblemCode.RESULT_STALE,"request/snapshot stale")
  if set(s.equipment)!={"body","main_hand","utility"} or set(s.permissions)!=_ACTIONS or any(not isinstance(v,bool) for v in s.permissions.values()):return self._blocked(r,ProblemCode.RESULT_STALE,"equipment/permissions invalid")
  permission=s.permission_receipt;permission_fields={"schema","receipt_ref","actor_ref","owner_ref","inventory_ref","room_revision","actor_revision","inventory_revision","allowed_actions","expires_at","dedupe_key","fingerprint"}
  if set(permission)!=permission_fields or permission.get("schema")!="platform-inventory-permission-receipt/1.0.0" or permission.get("actor_ref")!=s.actor_ref or permission.get("owner_ref")!=s.owner_ref or permission.get("inventory_ref")!=s.inventory_ref or permission.get("room_revision")!=s.room_revision or permission.get("actor_revision")!=s.actor_revision or permission.get("inventory_revision")!=s.inventory_revision or list(permission.get("allowed_actions",()))!=sorted(k for k,v in s.permissions.items() if v) or permission.get("fingerprint")!=canonical_fingerprint({k:_plain(v) for k,v in permission.items() if k!="fingerprint"}):return self._blocked(r,ProblemCode.RESULT_STALE,"permission receipt invalid")
  try:
   for key in ("receipt_ref","actor_ref","owner_ref","inventory_ref","dedupe_key"):_ref(permission[key],key)
   _hash(permission["fingerprint"],"fingerprint");permission_expiry=datetime.fromisoformat(permission["expires_at"].replace("Z","+00:00"));request_deadline=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  except (InventoryEquipmentContractError,AttributeError,ValueError):return self._blocked(r,ProblemCode.INPUT_INVALID,"permission receipt fields invalid")
  if permission_expiry.tzinfo is None or permission_expiry<request_deadline:return self._blocked(r,ProblemCode.RESULT_STALE,"permission expires before operation")
  cause_fields={"schema","receipt_ref","cause_ref","room_ref","actor_ref","inventory_ref","room_revision","actor_revision","inventory_revision","dedupe_key","committed","fingerprint"}
  for cause in s.cause_receipts:
   if not isinstance(cause,Mapping) or set(cause)!=cause_fields or cause.get("schema")!="platform-inventory-cause-receipt/1.0.0" or cause.get("committed") is not True or cause.get("room_ref")!=s.room_ref or cause.get("actor_ref")!=s.actor_ref or cause.get("inventory_ref")!=s.inventory_ref or cause.get("room_revision")!=s.room_revision or cause.get("actor_revision")!=s.actor_revision or cause.get("inventory_revision")!=s.inventory_revision or cause.get("fingerprint")!=canonical_fingerprint({k:_plain(v) for k,v in cause.items() if k!="fingerprint"}) or cause.get("dedupe_key") in s.consumed_dedupe_keys:return self._blocked(r,ProblemCode.RESULT_STALE,"cause receipt invalid/consumed")
   try:
    for key in ("receipt_ref","cause_ref","room_ref","actor_ref","inventory_ref","dedupe_key"):_ref(cause[key],key)
    _hash(cause["fingerprint"],"fingerprint")
   except InventoryEquipmentContractError:return self._blocked(r,ProblemCode.INPUT_INVALID,"cause receipt identity invalid")
  for instance_ref,instance in s.instances.items():
   definition=self.definitions.get(instance.get("item_ref")) if isinstance(instance,Mapping) else None
   try:_ref(instance_ref,"instance_ref")
   except InventoryEquipmentContractError:return self._blocked(r,ProblemCode.RESULT_STALE,"instance ref invalid")
   if definition is None or set(instance)!={"item_ref","definition_sha256","owner_ref","container_ref","quantity","durability","equipped_slot","binding_receipt_ref"} or instance["definition_sha256"]!=definition["definition_sha256"] or instance["owner_ref"]!=s.owner_ref or instance["container_ref"] is not None or isinstance(instance["quantity"],bool) or not isinstance(instance["quantity"],int) or instance["quantity"]<=0 or definition["stack_policy"]=="unique" and instance["quantity"]!=1 or definition["instance_template"]["durability_max"] is not None and (isinstance(instance["durability"],bool) or not isinstance(instance["durability"],int) or not 0<=instance["durability"]<=definition["instance_template"]["durability_max"]) or definition["instance_template"]["durability_max"] is None and instance["durability"] is not None:return self._blocked(r,ProblemCode.RESULT_STALE,"instance state invalid")
  if any(value is not None and (value not in s.instances or s.instances[value]["equipped_slot"]!=slot) for slot,value in s.equipment.items()):return self._blocked(r,ProblemCode.RESULT_STALE,"equipment binding invalid")
  if any(instance["equipped_slot"] is not None and s.equipment.get(instance["equipped_slot"])!=ref for ref,instance in s.instances.items()):return self._blocked(r,ProblemCode.RESULT_STALE,"reverse equipment binding invalid")
  shapes={InventoryAction.INSPECT:{"instance_ref"},InventoryAction.TRANSFER:{"instance_ref","target_owner_ref"},InventoryAction.SPLIT:{"instance_ref","quantity"},InventoryAction.MERGE:{"source_instance_ref","target_instance_ref"},InventoryAction.EQUIP:{"instance_ref","slot"},InventoryAction.UNEQUIP:{"instance_ref"},InventoryAction.USE:{"instance_ref","target_ref","target_kind","effect_index"},InventoryAction.CONSUME:{"instance_ref","quantity"},InventoryAction.DROP:{"instance_ref","quantity"},InventoryAction.REPAIR:{"instance_ref"}}
  if set(r.input)!=shapes[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action shape invalid")
  instance_ref=r.input.get("instance_ref") or r.input.get("source_instance_ref");inst=s.instances.get(instance_ref);definition=None if inst is None else self.definitions.get(inst.get("item_ref"))
  if inst is None or definition is None or inst.get("owner_ref")!=s.owner_ref:return self._blocked(r,ProblemCode.RESULT_STALE,"instance/owner invalid")
  quantity=inst.get("quantity");durability=inst.get("durability");slot=inst.get("equipped_slot");public_label=definition["label"] if definition["visibility"]=="public" or s.actor_ref==s.owner_ref else "Physical item present";public={"item_label":public_label,"action":r.action.value,"availability":True,"quantity":quantity,"durability":durability,"slot":slot,"visibility":definition["visibility"]};base={"base_inventory_revision":s.inventory_revision,"instance_ref":instance_ref,"item_ref":definition["item_ref"],"definition_sha256":definition["definition_sha256"],"owner_ref":s.owner_ref,"platform_commit_required":True}
  if not s.permissions.get(r.action.value,False):return self._blocked(r,ProblemCode.INPUT_INVALID,"action permission unavailable")
  if r.action is InventoryAction.INSPECT:return self._proposal(r,InventoryProposalKind.INSPECT,public,{**base,"read_only":True})
  if r.action is InventoryAction.TRANSFER:
   if slot is not None or definition["binding_policy"]!="unbound" or r.input["target_owner_ref"]==s.owner_ref:return self._invalid(r,public,"item_equipped_bound_or_same_owner")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"transfer","target_owner_ref":r.input["target_owner_ref"],"preserve_instance_ref":True})
  if r.action is InventoryAction.SPLIT:
   q=r.input["quantity"]
   if slot is not None or definition["stack_policy"]!="stackable" or isinstance(q,bool) or not isinstance(q,int) or not 0<q<quantity:return self._invalid(r,public,"split_invalid")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"split","split_quantity":q,"new_instance_ref":None})
  if r.action is InventoryAction.MERGE:
   target=s.instances.get(r.input["target_instance_ref"])
   if r.input["target_instance_ref"]==instance_ref or slot is not None or definition["stack_policy"]!="stackable" or target is None or target.get("equipped_slot") is not None or target.get("item_ref")!=definition["item_ref"] or target.get("owner_ref")!=s.owner_ref:return self._invalid(r,public,"merge_invalid")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"merge","target_instance_ref":r.input["target_instance_ref"],"source_quantity":quantity,"target_quantity":target["quantity"],"merged_quantity":target["quantity"]+quantity,"remove_source_after_commit":True})
  if r.action is InventoryAction.EQUIP:
   target_slot=r.input["slot"]
   if definition["slot"]=="none" or target_slot!=definition["slot"] or s.equipment.get(target_slot) not in {None,instance_ref}:return self._invalid(r,public,"equip_slot_invalid")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"equip","slot":target_slot,"expected_slot_instance_ref":s.equipment.get(target_slot)})
  if r.action is InventoryAction.UNEQUIP:
   if slot not in {"body","main_hand","utility"} or s.equipment.get(slot)!=instance_ref:return self._invalid(r,public,"unequip_invalid")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"unequip","slot":slot})
  if r.action is InventoryAction.USE:
   i=r.input["effect_index"]
   if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(definition["use_effects"]):return self._invalid(r,public,"use_unavailable")
   effect=definition["use_effects"][i]
   if r.input["target_kind"] not in effect["target_kinds"] or durability is None or durability<effect["durability_cost"]:return self._invalid(r,public,"use_target_or_durability_invalid")
   return self._proposal(r,InventoryProposalKind.EFFECT,public,{**base,"operation":"use","effect":_plain(effect),"target_ref":r.input["target_ref"],"target_kind":r.input["target_kind"],"set_durability":durability-effect["durability_cost"],"atomic_effect_and_cost":True})
  if r.action is InventoryAction.CONSUME:
   if not definition["instance_template"]["consume_available"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"consume unavailable")
  if r.action is InventoryAction.REPAIR:
   if not definition["instance_template"]["repair_available"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"repair unavailable")
  if r.action is InventoryAction.DROP:
   q=r.input["quantity"]
   if isinstance(q,bool) or not isinstance(q,int) or not 0<q<=quantity or slot is not None:return self._invalid(r,public,"drop invalid")
   return self._proposal(r,InventoryProposalKind.MUTATION,public,{**base,"operation":"drop","quantity":q,"physical_visibility_preserved":True})
  return self._blocked(r,ProblemCode.INPUT_INVALID,"operation unavailable")
 def _proposal(self,r,kind,public,private,status=InventoryStatus.PROPOSED,errors=()):
  p=InventoryProposal(INVENTORY_PROPOSAL_SCHEMA,"inventory."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.inventory_revision,kind,public,private,tuple(errors));x=InventoryResult(INVENTORY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.inventory_revision,status,p);return replace(x,result_fingerprint=inventory_result_fingerprint(x))
 def _invalid(self,r,public,error):return self._proposal(r,InventoryProposalKind.VALIDATION,public,None,InventoryStatus.INVALID,(error,))
 def _blocked(self,r,code,reason):
  p=Problem(code,"evaluate inventory equipment",reason,"no inventory proposal committed","refresh inventory snapshot");x=InventoryResult(INVENTORY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.inventory_revision,InventoryStatus.BLOCKED,problems=(p,));return replace(x,result_fingerprint=inventory_result_fingerprint(x))
class InventoryEquipmentService:
 def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
 async def evaluate_inventory_equipment(self,r,bridge):
  c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);deadline=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,InventoryStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,InventoryStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  x=self.evaluator.evaluate(r)
  if(await bridge.is_cancelled(c)).cancelled:return self._terminal(r,InventoryStatus.CANCELLED,ProblemCode.CANCELLED)
  if self.clock()>=deadline:return self._terminal(r,InventoryStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
  return x
 def _terminal(self,r,status,code):
  p=Problem(code,"evaluate inventory equipment","cancelled/deadline","no proposal","retry fresh");x=InventoryResult(INVENTORY_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.inventory_revision,status,problems=(p,));return replace(x,result_fingerprint=inventory_result_fingerprint(x))
class InventoryEquipmentStoryEnginePort(Protocol):
 async def evaluate_inventory_equipment(self,request:InventoryRequest,bridge:PlatformBridge)->InventoryResult:...
