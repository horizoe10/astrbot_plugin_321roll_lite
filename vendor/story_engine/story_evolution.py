"""Strict unassigned StoryEvolution author-source, Definition, IR and proposal contracts.

Engine only compiles and proposes batch-local references. The platform owns policy,
stable IDs, commits, recovery, projections, and every StoryFlow transition.
"""
from __future__ import annotations
import asyncio, hashlib, json, re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from .contracts.port import ModelInvocationRequest, ModelInvocationResult, ModelPurpose, PlatformBridge

AUTHOR_SOURCE_SCHEMA="sp-story-evolution-definition-candidate/0.2"
STORY_EVOLUTION_DEFINITION_SCHEMA="se-story-evolution-definition/1.0.0"
STORY_EVOLUTION_IR_SCHEMA="se-story-evolution-ir/1.0.0"
STORY_EVOLUTION_CONTEXT_SCHEMA="se-story-evolution-context/1.0.0"
STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA="story-evolution-proposals/1.0.0"
STORY_EVOLUTION_MODEL_OUTPUT_SCHEMA="se-story-evolution-model-output/1.0.0"
STORY_EVOLUTION_REQUIRED_MODEL_CAPABILITIES=frozenset({"structured_output"})
CAPABILITIES=("story.evolution.bounded/1","story.evolution.dynamic_graph/1")
DIRECTIONS=("guided_opening","free_evolution"); AMPLITUDES=("restrained","fluid","wild")
PRIORITY_OBJECT_TYPES={"P0":("story_thread","local_truth","evidence","future_direction"),"P1":("dynamic_scene","dynamic_actor","dynamic_graph_node","dynamic_graph_edge")}
OBJECT_TYPES=frozenset((*PRIORITY_OBJECT_TYPES["P0"],*PRIORITY_OBJECT_TYPES["P1"]))
AUDIENCES=frozenset({"public","player","player_specific","host","owner","author_offline"})
PURPOSES=frozenset({"turn_resolution","event_evaluation","world_reaction","future_direction"})
GRAPH_ABIS=frozenset({"none","dynamic-story-graph/1"})
BOUNDED_PROPOSAL_TYPES=frozenset({"static_anchor.suggest","static_module.suggest","character_reaction.suggest","narrative_focus.suggest"})
PROPOSAL_PRIORITY={"story_thread.open":"P0","story_thread.transition":"P0","local_truth.freeze":"P0","evidence.extend":"P0","future_direction.offer":"P0","dynamic_scene.propose":"P1","dynamic_actor.propose":"P1","dynamic_graph_node.propose":"P1","dynamic_graph_edge.propose":"P1"}
PROPOSAL_OBJECT={k:k.split(".",1)[0] for k in PROPOSAL_PRIORITY}; PROPOSAL_OBJECT["evidence.extend"]="evidence"
BUDGET_FIELDS=("max_new_objects_per_turn","max_p0_new_objects_per_turn","max_p1_new_objects_per_turn","max_active_story_threads","max_pending_future_directions","max_dynamic_actors","max_unresolved_local_truths","max_evidence_items","max_dynamic_graph_depth","max_story_flow_anchor_distance","min_operations_between_world_reactions")
_REF=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}$"); _LOCAL=re.compile(r"^local\.[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"); _DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_FIELDS={"schema","candidate_version","installable","definition_ref","locale","source_catalog_path","source_catalog_sha256","story_flow_recipe_path","story_flow_recipe_sha256","requirement_refs","capability","defaults","allowed","object_priority_tiers","generation_scopes","audience_boundary","story_flow_boundary","hard_facts","budgets_by_policy","opening_seeds","fallback"}

@dataclass(frozen=True,slots=True)
class StoryEvolutionContractError(ValueError):
    code:str; path:str; reason:str
    def __str__(self)->str:return f"{self.code}:{self.path}"
def _fail(code:str,path:str,reason:str)->None:raise StoryEvolutionContractError(code,path,reason)
def _obj(v:object,p:str)->Mapping[str,Any]:
    if not isinstance(v,Mapping):_fail("story_evolution.object_invalid",p,"expected object")
    return v
def _seq(v:object,p:str)->Sequence[Any]:
    if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("story_evolution.sequence_invalid",p,"expected array")
    return v
def _fields(v:Mapping[str,Any],e:set[str],p:str)->None:
    if set(v)!=e:_fail("story_evolution.fields_invalid",p,"missing or unknown fields")
def _text(v:object,p:str,n:int=800)->str:
    if not isinstance(v,str) or not v.strip() or len(v.strip())>n:_fail("story_evolution.text_invalid",p,"invalid text")
    return v.strip()
def _ref(v:object,p:str)->str:
    v=_text(v,p,200)
    if not _REF.fullmatch(v):_fail("story_evolution.reference_invalid",p,"invalid ref")
    return v
def _local(v:object,p:str)->str:
    v=_text(v,p,86)
    if not _LOCAL.fullmatch(v):_fail("story_evolution.local_reference_invalid",p,"local ref required")
    return v
def _integer(v:object,p:str,lo:int=0,hi:int=1000000)->int:
    if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:_fail("story_evolution.integer_invalid",p,"integer out of range")
    return v
def _refs(v:object,p:str,required:bool=False)->list[str]:
    out=[_ref(x,f"{p}[{i}]") for i,x in enumerate(_seq(v,p))]
    if required and not out:_fail("story_evolution.references_empty",p,"refs required")
    if len(out)!=len(set(out)):_fail("story_evolution.reference_duplicate",p,"duplicate")
    return sorted(out)
def _digest(v:Any)->str:
    try:b=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    except (TypeError,ValueError) as e:_fail("story_evolution.non_canonical_value","$",str(e))
    return "sha256:"+hashlib.sha256(b).hexdigest()
def _digest_value(v:object,p:str)->str:
    if not isinstance(v,str) or not _DIGEST.fullmatch(v):_fail("story_evolution.digest_invalid",p,"invalid digest")
    return v
def _budget(v:object,p:str)->dict[str,Any]:
    raw=_obj(v,p);_fields(raw,{"direction","amplitude",*BUDGET_FIELDS},p)
    if raw["direction"] not in DIRECTIONS or raw["amplitude"] not in AMPLITUDES:_fail("story_evolution.policy_invalid",p,"bad policy")
    out={k:_integer(raw[k],f"{p}.{k}",0,1000) for k in BUDGET_FIELDS}
    if any(out[k]==0 for k in BUDGET_FIELDS[3:]):_fail("story_evolution.budget_invalid",p,"positive capacity required")
    if out[BUDGET_FIELDS[0]]!=out[BUDGET_FIELDS[1]]+out[BUDGET_FIELDS[2]]:_fail("story_evolution.budget_partition_invalid",p,"P0+P1 != total")
    return {"direction":raw["direction"],"amplitude":raw["amplitude"],**out}

def project_story_evolution_author_source(source:Mapping[str,Any],coverage:Mapping[str,Any],story_flow_recipe:Mapping[str,Any],openings_catalog:Mapping[str,Any],dependency_digests:Mapping[str,Any])->dict[str,Any]:
    """Strict SP candidate -> public SE Definition projection."""
    raw=_obj(source,"$");_fields(raw,_SOURCE_FIELDS,"$")
    if raw["schema"]!=AUTHOR_SOURCE_SCHEMA or raw["candidate_version"]!="unassigned" or raw["installable"] is not False:_fail("story_evolution.author_identity_invalid","$","candidate identity")
    cap=_obj(raw["capability"],"capability");_fields(cap,{"required","optional"},"capability")
    if _refs(cap["required"],"capability.required")!=[CAPABILITIES[0]] or _refs(cap["optional"],"capability.optional")!=[CAPABILITIES[1]]:_fail("story_evolution.capability_invalid","capability","frozen split")
    defaults=_obj(raw["defaults"],"defaults");_fields(defaults,{"direction","amplitude"},"defaults")
    allowed=_obj(raw["allowed"],"allowed");_fields(allowed,{"directions","amplitudes"},"allowed")
    if list(_seq(allowed["directions"],"allowed.directions"))!=list(DIRECTIONS) or list(_seq(allowed["amplitudes"],"allowed.amplitudes"))!=list(AMPLITUDES) or defaults["direction"] not in DIRECTIONS or defaults["amplitude"] not in AMPLITUDES:_fail("story_evolution.policy_invalid","allowed","six combinations required")
    tiers=_obj(raw["object_priority_tiers"],"object_priority_tiers");_fields(tiers,{"P0","P1"},"object_priority_tiers")
    for pr in ("P0","P1"):
        if tuple(_seq(tiers[pr],f"object_priority_tiers.{pr}"))!=PRIORITY_OBJECT_TYPES[pr]:_fail("story_evolution.priority_tier_invalid",f"object_priority_tiers.{pr}","frozen tier")
    scopes=_obj(raw["generation_scopes"],"generation_scopes");_fields(scopes,set(OBJECT_TYPES),"generation_scopes");scope_out={}
    for kind in sorted(OBJECT_TYPES):
        s=_obj(scopes[kind],f"generation_scopes.{kind}");_fields(s,{"purpose","source_domains","audiences","lifecycle"},f"generation_scopes.{kind}")
        audiences=list(_seq(s["audiences"],f"generation_scopes.{kind}.audiences"))
        if not audiences or len(audiences)!=len(set(audiences)) or set(audiences)-AUDIENCES:_fail("story_evolution.audience_invalid",f"generation_scopes.{kind}.audiences","invalid")
        scope_out[kind]={"priority":"P0" if kind in PRIORITY_OBJECT_TYPES["P0"] else "P1","purpose":_text(s["purpose"],f"generation_scopes.{kind}.purpose"),"source_domains":_refs(s["source_domains"],f"generation_scopes.{kind}.source_domains",True),"audiences":audiences,"lifecycle":_refs(s["lifecycle"],f"generation_scopes.{kind}.lifecycle",True)}
    audience=_obj(raw["audience_boundary"],"audience_boundary");_fields(audience,{"allowed_audiences","default","rules"},"audience_boundary")
    if set(_seq(audience["allowed_audiences"],"audience_boundary.allowed_audiences"))!=AUDIENCES or audience["default"] not in AUDIENCES:_fail("story_evolution.audience_invalid","audience_boundary","closure")
    audience_out={"allowed_audiences":list(audience["allowed_audiences"]),"default":audience["default"],"rules":[_text(x,"audience_boundary.rules[]") for x in _seq(audience["rules"],"audience_boundary.rules")]}
    flow=_obj(raw["story_flow_boundary"],"story_flow_boundary");flow_fields={"recipe_ref","allowed_phase_kinds","allowed_anchor_roles","static_nodes_and_transitions_immutable","dynamic_content_may_reference_anchor","dynamic_content_may_change_phase","dynamic_content_may_replace_static_transition","required_opening_outcomes"};_fields(flow,flow_fields,"story_flow_boundary")
    if flow["static_nodes_and_transitions_immutable"] is not True or flow["dynamic_content_may_change_phase"] is not False or flow["dynamic_content_may_replace_static_transition"] is not False:_fail("story_evolution.story_flow_authority_violation","story_flow_boundary","cannot mutate StoryFlow")
    flow_out={"recipe_ref":_ref(flow["recipe_ref"],"story_flow_boundary.recipe_ref"),"allowed_phase_kinds":_refs(flow["allowed_phase_kinds"],"story_flow_boundary.allowed_phase_kinds",True),"allowed_anchor_roles":_refs(flow["allowed_anchor_roles"],"story_flow_boundary.allowed_anchor_roles",True),"static_nodes_and_transitions_immutable":True,"dynamic_content_may_reference_anchor":flow["dynamic_content_may_reference_anchor"] is True,"dynamic_content_may_change_phase":False,"dynamic_content_may_replace_static_transition":False,"required_opening_outcomes":_refs(flow["required_opening_outcomes"],"story_flow_boundary.required_opening_outcomes",True)}
    facts=[]
    for i,x in enumerate(_seq(raw["hard_facts"],"hard_facts")):
        f=_obj(x,f"hard_facts[{i}]");_fields(f,{"fact_ref","statement","audience","source_ref","conflict_category"},f"hard_facts[{i}]")
        if f["audience"] not in AUDIENCES:_fail("story_evolution.audience_invalid",f"hard_facts[{i}]","fact audience")
        facts.append({"fact_ref":_ref(f["fact_ref"],"fact_ref"),"statement":_text(f["statement"],"statement"),"audience":f["audience"],"source_ref":_ref(f["source_ref"],"source_ref"),"conflict_category":_ref(f["conflict_category"],"conflict_category")})
    if not facts or len({x["fact_ref"] for x in facts})!=len(facts):_fail("story_evolution.hard_fact_invalid","hard_facts","unique facts required")
    budgets=[_budget(x,f"budgets_by_policy[{i}]") for i,x in enumerate(_seq(raw["budgets_by_policy"],"budgets_by_policy"))]
    if len(budgets)!=6 or {(x["direction"],x["amplitude"]) for x in budgets}!={(d,a) for d in DIRECTIONS for a in AMPLITUDES}:_fail("story_evolution.budget_matrix_incomplete","budgets_by_policy","six rows")
    seeds=[];seed_fields={"seed_ref","source_opening_id","story_flow_opening_ref","story_flow_entry_node_ref","story_flow_anchor_node_ref","title","region","public_premise","dynamic_gap","allowed_priorities"}
    for i,x in enumerate(_seq(raw["opening_seeds"],"opening_seeds")):
        s=_obj(x,f"opening_seeds[{i}]");_fields(s,seed_fields,f"opening_seeds[{i}]")
        if list(_seq(s["allowed_priorities"],"allowed_priorities"))!=["P0","P1"]:_fail("story_evolution.seed_priority_invalid",f"opening_seeds[{i}]","P0/P1 required")
        seeds.append({k:(["P0","P1"] if k=="allowed_priorities" else _text(s[k],k) if k in {"title","region","public_premise","dynamic_gap"} else _ref(s[k],k)) for k in seed_fields})
    if not seeds or len({x["seed_ref"] for x in seeds})!=len(seeds):_fail("story_evolution.opening_seed_invalid","opening_seeds","unique seeds")
    fallback=_obj(raw["fallback"],"fallback");fb_fields={"dynamic_graph_unavailable","structured_output_unavailable","object_type_unavailable","budget_exhausted","playable_recipe_ref","player_summary"};_fields(fallback,fb_fields,"fallback")
    allowed_fb={"bounded_routes","static_anchor_only","block_start"}
    if any(fallback[k] not in allowed_fb for k in ("dynamic_graph_unavailable","structured_output_unavailable","object_type_unavailable","budget_exhausted")):_fail("story_evolution.fallback_invalid","fallback","bad fallback")
    cov=_obj(coverage,"coverage");_fields(cov,{"schema","candidate_version","installable","definition_ref","source_catalog_path","source_catalog_sha256","story_flow_recipe_path","story_flow_recipe_sha256","counts","openings"},"coverage")
    if cov["schema"]!="sp-story-evolution-coverage-candidate/0.2" or cov["candidate_version"]!="unassigned" or cov["installable"] is not False or cov["definition_ref"]!=raw["definition_ref"]:_fail("story_evolution.coverage_identity_invalid","coverage","identity mismatch")
    expected_counts={"source_openings":len(seeds),"opening_seeds":len(seeds),"story_flow_entry_nodes":len(seeds),"story_flow_anchor_nodes":len(seeds),"p0_object_types":4,"p1_object_types":4,"hard_facts":len(facts),"policy_budget_combinations":6}
    counts=_obj(cov["counts"],"coverage.counts");_fields(counts,set(expected_counts),"coverage.counts")
    if dict(counts)!=expected_counts:_fail("story_evolution.coverage_count_mismatch","coverage.counts","count drift")
    seed_map={x["source_opening_id"]:x for x in seeds};covered=set()
    for i,x in enumerate(_seq(cov["openings"],"coverage.openings")):
        item=_obj(x,f"coverage.openings[{i}]");_fields(item,{"source_opening_id","seed_ref","story_flow_opening_ref","story_flow_entry_node_ref","story_flow_anchor_node_ref","p0_covered","p1_covered","hard_fact_boundary_covered","audience_boundary_covered"},f"coverage.openings[{i}]");sid=item["source_opening_id"]
        if sid not in seed_map or sid in covered or any(item[k]!=seed_map[sid][k] for k in ("seed_ref","story_flow_opening_ref","story_flow_entry_node_ref","story_flow_anchor_node_ref")) or any(item[k] is not True for k in ("p0_covered","p1_covered","hard_fact_boundary_covered","audience_boundary_covered")):_fail("story_evolution.coverage_opening_mismatch",f"coverage.openings[{i}]","opening drift")
        covered.add(sid)
    if covered!=set(seed_map):_fail("story_evolution.coverage_opening_mismatch","coverage.openings","incomplete")
    digests=_obj(dependency_digests,"dependency_digests");_fields(digests,{"source_catalog_sha256","story_flow_recipe_sha256"},"dependency_digests")
    expected_paths={"source_catalog_path":"author/se1/openings_and_routes.json","story_flow_recipe_path":"author/se1/v02/story_flow_recipe.json"}
    if any(raw[k]!=v or cov[k]!=v for k,v in expected_paths.items()):_fail("story_evolution.coverage_path_invalid","coverage","author dependency paths are frozen")
    for key in ("source_catalog_sha256","story_flow_recipe_sha256"):
        expected_digest=_digest_value(digests[key],f"dependency_digests.{key}")
        if raw[key]!=expected_digest or cov[key]!=expected_digest:_fail("story_evolution.author_dependency_digest_mismatch",key,"author dependency digest drift")
    flow_recipe=_obj(story_flow_recipe,"story_flow_recipe");catalog=_obj(openings_catalog,"openings_catalog")
    if flow_recipe.get("recipe_ref")!=flow_out["recipe_ref"] or not isinstance(flow_recipe.get("opening_entries"),list) or not isinstance(catalog.get("openings"),list):_fail("story_evolution.author_dependency_invalid","story_flow_recipe","missing authoritative recipe/catalog")
    catalog_ids={item.get("id") for item in catalog["openings"] if isinstance(item,Mapping)}
    flow_entries={item.get("source_opening_id"):item for item in flow_recipe["opening_entries"] if isinstance(item,Mapping)}
    for seed in seeds:
        entry=flow_entries.get(seed["source_opening_id"])
        if seed["source_opening_id"] not in catalog_ids or entry is None or entry.get("opening_ref")!=seed["story_flow_opening_ref"] or entry.get("entry_node_ref")!=seed["story_flow_entry_node_ref"] or entry.get("first_chapter_node_ref")!=seed["story_flow_anchor_node_ref"]:_fail("story_evolution.author_dependency_mismatch",seed["seed_ref"],"seed refs not in authoritative StoryFlow/opening closure")
    if set(seed_map)!=catalog_ids or set(seed_map)!=set(flow_entries):_fail("story_evolution.author_dependency_mismatch","opening_seeds","author dependency closure differs")
    source_sha=_digest(raw);coverage_sha=_digest(cov);story_flow_sha=digests["story_flow_recipe_sha256"];openings_sha=digests["source_catalog_sha256"]
    out={"schema":STORY_EVOLUTION_DEFINITION_SCHEMA,"source_schema":AUTHOR_SOURCE_SCHEMA,"candidate_version":"unassigned","installable":False,"definition_ref":_ref(raw["definition_ref"],"definition_ref"),"locale":_ref(raw["locale"],"locale"),"requirement_refs":_refs(raw["requirement_refs"],"requirement_refs",True),"capability":{"required":[CAPABILITIES[0]],"optional":[CAPABILITIES[1]]},"defaults":dict(defaults),"allowed":{"directions":list(DIRECTIONS),"amplitudes":list(AMPLITUDES)},"object_priority_tiers":{"P0":list(PRIORITY_OBJECT_TYPES["P0"]),"P1":list(PRIORITY_OBJECT_TYPES["P1"])},"generation_scopes":scope_out,"audience_boundary":audience_out,"story_flow_boundary":flow_out,"hard_facts":sorted(facts,key=lambda x:x["fact_ref"]),"budgets_by_policy":sorted(budgets,key=lambda x:(DIRECTIONS.index(x["direction"]),AMPLITUDES.index(x["amplitude"]))),"opening_seeds":sorted(seeds,key=lambda x:x["seed_ref"]),"fallback":dict(fallback),"source_sha256":source_sha,"coverage_sha256":coverage_sha,"story_flow_recipe_sha256":story_flow_sha,"openings_catalog_sha256":openings_sha}
    out["definition_sha256"]=_digest(out);return out

def compile_story_evolution_definition(definition:Mapping[str,Any])->dict[str,Any]:
    raw=_obj(definition,"$");expected=(_SOURCE_FIELDS-{"schema","source_catalog_path","source_catalog_sha256","story_flow_recipe_path","story_flow_recipe_sha256"})|{"schema","source_schema","source_sha256","coverage_sha256","story_flow_recipe_sha256","openings_catalog_sha256","definition_sha256"};_fields(raw,expected,"$")
    if raw["schema"]!=STORY_EVOLUTION_DEFINITION_SCHEMA or raw["source_schema"]!=AUTHOR_SOURCE_SCHEMA or raw["installable"] is not False:_fail("story_evolution.definition_identity_invalid","$","identity")
    if raw["definition_sha256"]!=_digest({k:v for k,v in raw.items() if k!="definition_sha256"}):_fail("story_evolution.definition_digest_mismatch","definition_sha256","drift")
    keys={"definition_ref","capability","defaults","allowed","object_priority_tiers","generation_scopes","audience_boundary","story_flow_boundary","hard_facts","budgets_by_policy","opening_seeds","fallback"};runtime={k:raw[k] for k in sorted(keys)}
    out={"schema":STORY_EVOLUTION_IR_SCHEMA,"definition_ref":raw["definition_ref"],"definition_sha256":raw["definition_sha256"],"source_sha256":raw["source_sha256"],"coverage_sha256":raw["coverage_sha256"],"story_flow_recipe_sha256":raw["story_flow_recipe_sha256"],"openings_catalog_sha256":raw["openings_catalog_sha256"],"candidate_version":"unassigned","installable":False,"runtime_slice":runtime,"runtime_slice_sha256":_digest(runtime)};out["ir_sha256"]=_digest(out);return out
def validate_story_evolution_ir(ir:Mapping[str,Any],definition:Mapping[str,Any])->None:
    raw=_obj(ir,"$");_fields(raw,{"schema","definition_ref","definition_sha256","source_sha256","coverage_sha256","story_flow_recipe_sha256","openings_catalog_sha256","candidate_version","installable","runtime_slice","runtime_slice_sha256","ir_sha256"},"$")
    if raw["runtime_slice_sha256"]!=_digest(raw["runtime_slice"]) or raw["ir_sha256"]!=_digest({k:v for k,v in raw.items() if k!="ir_sha256"}):_fail("story_evolution.digest_mismatch","$","IR digest")
    if dict(raw)!=compile_story_evolution_definition(definition):_fail("story_evolution.product_mismatch","$","recompile mismatch")
def make_story_evolution_request_fingerprint(v:Mapping[str,Any])->str:
    if "request_fingerprint" in v:_fail("story_evolution.fingerprint_input_invalid","$","remove fingerprint")
    return _digest(v)

def validate_story_evolution_context(context:Mapping[str,Any],ir:Mapping[str,Any])->None:
    raw=_obj(context,"$");_fields(raw,{"schema","operation_ref","purpose","capability","policy","story_flow","pins","base_story_revision","base_graph_revision","safe_context","request_fingerprint"},"$")
    if raw["schema"]!=STORY_EVOLUTION_CONTEXT_SCHEMA or raw["capability"] not in CAPABILITIES:_fail("story_evolution.context_identity_invalid","$","identity")
    _ref(raw["operation_ref"],"operation_ref")
    if not isinstance(raw["purpose"],str) or raw["purpose"] not in PURPOSES:_fail("story_evolution.purpose_invalid","purpose","unknown purpose")
    _integer(raw["base_story_revision"],"base_story_revision")
    _integer(raw["base_graph_revision"],"base_graph_revision")
    runtime=ir["runtime_slice"];policy=_obj(raw["policy"],"policy");_fields(policy,{"direction","amplitude","object_type_allowlist","budget","hard_facts_sha256","seed_digest","rng_slice_ref","policy_revision","policy_fingerprint"},"policy")
    if policy["direction"] not in DIRECTIONS or policy["amplitude"] not in AMPLITUDES:_fail("story_evolution.policy_invalid","policy","unknown direction/amplitude")
    allow=list(_seq(policy["object_type_allowlist"],"policy.object_type_allowlist"));expected_allow=set(PRIORITY_OBJECT_TYPES["P0"] if raw["capability"]==CAPABILITIES[0] else OBJECT_TYPES)
    if any(not isinstance(kind,str) or kind not in OBJECT_TYPES for kind in allow):_fail("story_evolution.object_allowlist_closure_invalid","policy.object_type_allowlist","unknown object type")
    if len(allow)!=len(set(allow)) or set(allow)!=expected_allow:_fail("story_evolution.object_allowlist_closure_invalid","policy.object_type_allowlist","allowlist must exactly equal capability closure")
    budget=_budget(policy["budget"],"policy.budget")
    if budget["direction"]!=policy["direction"] or budget["amplitude"]!=policy["amplitude"]:_fail("story_evolution.policy_budget_mismatch","policy.budget","nested budget policy differs from top policy")
    matching=[x for x in runtime["budgets_by_policy"] if x["direction"]==policy["direction"] and x["amplitude"]==policy["amplitude"]]
    if len(matching)!=1:_fail("story_evolution.policy_invalid","policy","policy budget is absent or ambiguous in IR")
    ceiling=matching[0]
    if any(budget[k]>ceiling[k] for k in BUDGET_FIELDS):_fail("story_evolution.budget_exceeds_ir","policy.budget","widened")
    if policy["hard_facts_sha256"]!=_digest(runtime["hard_facts"]):_fail("story_evolution.policy_digest_mismatch","policy.hard_facts_sha256","drift")
    _digest_value(policy["seed_digest"],"policy.seed_digest")
    _ref(policy["rng_slice_ref"],"policy.rng_slice_ref")
    _integer(policy["policy_revision"],"policy.policy_revision")
    if policy["policy_fingerprint"]!=_digest({k:v for k,v in policy.items() if k!="policy_fingerprint"}):_fail("story_evolution.policy_fingerprint_mismatch","policy.policy_fingerprint","drift")
    flow=_obj(raw["story_flow"],"story_flow");_fields(flow,{"recipe_ref","phase_kind","phase_ref","lane_ref","audience","revision","fingerprint"},"story_flow")
    for key in ("recipe_ref","phase_kind","phase_ref","lane_ref"):_ref(flow[key],f"story_flow.{key}")
    if not isinstance(flow["audience"],str) or flow["audience"] not in AUDIENCES:_fail("story_evolution.audience_invalid","story_flow.audience","unknown audience")
    _integer(flow["revision"],"story_flow.revision")
    _digest_value(flow["fingerprint"],"story_flow.fingerprint")
    if flow["recipe_ref"]!=runtime["story_flow_boundary"]["recipe_ref"] or flow["phase_kind"] not in runtime["story_flow_boundary"]["allowed_phase_kinds"]:_fail("story_evolution.story_flow_scope_violation","story_flow","outside flow")
    pins=_obj(raw["pins"],"pins");_fields(pins,{"engine_sha256","story_pack_sha256","artifact_sha256","definition_ir_sha256","proposal_contract_version","dynamic_graph_abi"},"pins")
    for key in ("engine_sha256","story_pack_sha256","artifact_sha256","definition_ir_sha256"):_digest_value(pins[key],f"pins.{key}")
    if not isinstance(pins["dynamic_graph_abi"],str) or pins["dynamic_graph_abi"] not in GRAPH_ABIS:_fail("story_evolution.dynamic_graph_abi_invalid","pins.dynamic_graph_abi","unknown ABI")
    expected_abi="dynamic-story-graph/1" if raw["capability"]==CAPABILITIES[1] else "none"
    if pins["dynamic_graph_abi"]!=expected_abi:_fail("story_evolution.dynamic_graph_abi_mismatch","pins.dynamic_graph_abi","ABI does not match capability")
    if pins["definition_ir_sha256"]!=ir["ir_sha256"] or pins["proposal_contract_version"]!=STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA:_fail("story_evolution.pin_mismatch","pins","pin drift")
    safe=_obj(raw["safe_context"],"safe_context");_fields(safe,{"authorized_refs","available_anchor_refs","active_object_refs","current_object_counts"},"safe_context");_refs(safe["authorized_refs"],"safe_context.authorized_refs");_refs(safe["available_anchor_refs"],"safe_context.available_anchor_refs");_refs(safe["active_object_refs"],"safe_context.active_object_refs");counts=_obj(safe["current_object_counts"],"current_object_counts");_fields(counts,set(OBJECT_TYPES),"current_object_counts")
    for kind in OBJECT_TYPES:_integer(counts[kind],f"current_object_counts.{kind}")
    if raw["request_fingerprint"]!=_digest({k:v for k,v in raw.items() if k!="request_fingerprint"}):_fail("story_evolution.request_fingerprint_mismatch","request_fingerprint","drift")

def validate_evolution_proposal_batch(batch:Mapping[str,Any],context:Mapping[str,Any],ir:Mapping[str,Any])->None:
    validate_story_evolution_context(context,ir);raw=_obj(batch,"$");_fields(raw,{"contract_version","operation_ref","base_story_revision","base_graph_revision","request_fingerprint","policy_fingerprint","story_pack_sha256","artifact_sha256","capability","items","dependency_edges","narrative_dependency_refs","receipt","batch_sha256"},"$")
    expected={"operation_ref":context["operation_ref"],"base_story_revision":context["base_story_revision"],"base_graph_revision":context["base_graph_revision"],"request_fingerprint":context["request_fingerprint"],"policy_fingerprint":context["policy"]["policy_fingerprint"],"story_pack_sha256":context["pins"]["story_pack_sha256"],"artifact_sha256":context["pins"]["artifact_sha256"],"capability":context["capability"]}
    if raw["contract_version"]!=STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA or any(raw[k]!=v for k,v in expected.items()):_fail("story_evolution.batch_context_mismatch","$","context drift")
    known=[];items={};counts={"P0":0,"P1":0};authorized=set(context["safe_context"]["authorized_refs"]+context["safe_context"]["available_anchor_refs"]+context["safe_context"]["active_object_refs"])
    for i,x in enumerate(_seq(raw["items"],"items")):
        item=_obj(x,f"items[{i}]");_fields(item,{"proposal_local_ref","type","priority","audience","source_refs","depends_on","payload"},f"items[{i}]");lr=_local(item["proposal_local_ref"],"proposal_local_ref")
        if lr in items:_fail("story_evolution.local_reference_duplicate",f"items[{i}]","duplicate")
        priority="P0" if item["type"] in BOUNDED_PROPOSAL_TYPES else PROPOSAL_PRIORITY.get(item["type"])
        if priority is None:_fail("story_evolution.proposal_type_invalid",f"items[{i}].type","unknown")
        if item["priority"]!=priority:_fail("story_evolution.proposal_priority_mismatch",f"items[{i}].priority","tier mismatch")
        if priority=="P1" and context["capability"]!=CAPABILITIES[1]:_fail("story_evolution.p1_capability_required",f"items[{i}]","dynamic required")
        kind=PROPOSAL_OBJECT.get(item["type"]);scope=ir["runtime_slice"]["generation_scopes"].get(kind)
        if kind is not None and kind not in context["policy"]["object_type_allowlist"]:_fail("story_evolution.object_type_not_allowed",f"items[{i}].type","proposal object outside policy allowlist")
        if item["audience"] not in AUDIENCES or scope and item["audience"] not in scope["audiences"]:_fail("story_evolution.audience_widening",f"items[{i}].audience","outside scope")
        if set(_refs(item["source_refs"],"source_refs",True))-authorized:_fail("story_evolution.source_reference_unresolved",f"items[{i}].source_refs","unauthorized")
        deps=[_local(d,"depends_on") for d in _seq(item["depends_on"],"depends_on")]
        if set(deps)-set(known) or len(deps)!=len(set(deps)):_fail("story_evolution.dependency_invalid",f"items[{i}].depends_on","forward/cycle")
        payload=_obj(item["payload"],"payload")
        forbidden={"platform_id","stable_id","database_id","commit","committed","commit_status","patch","database_patch","phase_transition","story_flow_transition"}
        def reject_authority(value:Any,path:str)->None:
            if isinstance(value,Mapping):
                for key,nested in value.items():
                    normalized=str(key).lower().replace("-","_")
                    if normalized in forbidden or normalized.endswith("_platform_id") or normalized.startswith("commit_"):_fail("story_evolution.payload_forbidden",f"{path}.{key}","nested platform/commit authority field")
                    reject_authority(nested,f"{path}.{key}")
            elif isinstance(value,Sequence) and not isinstance(value,(str,bytes,bytearray)):
                for index,nested in enumerate(value):reject_authority(nested,f"{path}[{index}]")
        reject_authority(payload,f"items[{i}].payload")
        _fields(payload,{"summary","target_refs"},f"items[{i}].payload");_text(payload["summary"],f"items[{i}].payload.summary");payload_refs=_refs(payload["target_refs"],f"items[{i}].payload.target_refs")
        if {ref for ref in payload_refs if not ref.startswith("local.")}-authorized:_fail("story_evolution.payload_reference_unresolved",f"items[{i}].payload.target_refs","unauthorized payload ref")
        if {ref for ref in payload_refs if ref.startswith("local.")}-set(known):_fail("story_evolution.payload_local_reference_invalid",f"items[{i}].payload.target_refs","local payload refs must point backward")
        counts[priority]+=1;known.append(lr);items[lr]=item
    budget=context["policy"]["budget"]
    if len(items)>budget["max_new_objects_per_turn"] or counts["P0"]>budget["max_p0_new_objects_per_turn"] or counts["P1"]>budget["max_p1_new_objects_per_turn"]:_fail("story_evolution.creation_budget_exceeded","items","budget")
    proposed_counts={kind:sum(1 for item in items.values() if PROPOSAL_OBJECT.get(item["type"])==kind) for kind in OBJECT_TYPES};current=context["safe_context"]["current_object_counts"]
    capacity={"story_thread":"max_active_story_threads","future_direction":"max_pending_future_directions","dynamic_actor":"max_dynamic_actors","local_truth":"max_unresolved_local_truths","evidence":"max_evidence_items"}
    for kind,budget_key in capacity.items():
        if current[kind]+proposed_counts[kind]>budget[budget_key]:_fail("story_evolution.capacity_budget_exceeded",f"items.{kind}","active capacity exceeded")
    declared=set()
    for x in _seq(raw["dependency_edges"],"dependency_edges"):
        edge=_obj(x,"dependency_edges[]");_fields(edge,{"from_local_ref","to_local_ref"},"dependency_edges[]");declared.add((_local(edge["from_local_ref"],"from"),_local(edge["to_local_ref"],"to")))
    if declared!={(d,r) for r,x in items.items() for d in x["depends_on"]}:_fail("story_evolution.dependency_edge_mismatch","dependency_edges","mismatch")
    narr=[_local(x,"narrative_dependency_refs") for x in _seq(raw["narrative_dependency_refs"],"narrative_dependency_refs")]
    if set(narr)-set(items) or len(narr)!=len(set(narr)):_fail("story_evolution.narrative_dependency_invalid","narrative_dependency_refs","dangling")
    receipt=_obj(raw["receipt"],"receipt");_fields(receipt,{"status","proposal_count","p0_count","p1_count","model_call_count","policy_fingerprint","warnings","unused_reason"},"receipt")
    if receipt["status"] not in {"applied","no_change"} or (receipt["status"]=="no_change")!=(len(items)==0):_fail("story_evolution.receipt_status_invalid","receipt.status","no_change iff items empty; applied iff items non-empty")
    for key in ("proposal_count","p0_count","p1_count","model_call_count"):_integer(receipt[key],f"receipt.{key}")
    if receipt["proposal_count"]!=len(items) or receipt["p0_count"]!=counts["P0"] or receipt["p1_count"]!=counts["P1"] or receipt["policy_fingerprint"]!=context["policy"]["policy_fingerprint"]:_fail("story_evolution.receipt_mismatch","receipt","mismatch")
    warnings=_seq(receipt["warnings"],"receipt.warnings")
    for index,warning in enumerate(warnings):_text(warning,f"receipt.warnings[{index}]",240)
    if receipt["status"]=="no_change" and receipt["unused_reason"] is None:_fail("story_evolution.receipt_status_invalid","receipt.unused_reason","no_change requires reason")
    if receipt["status"]=="applied" and receipt["unused_reason"] is not None:_fail("story_evolution.receipt_status_invalid","receipt.unused_reason","applied cannot carry unused reason")
    if receipt["model_call_count"] not in {0,1}:_fail("story_evolution.model_call_budget_exceeded","receipt.model_call_count","calls")
    if raw["batch_sha256"]!=_digest({k:v for k,v in raw.items() if k!="batch_sha256"}):_fail("story_evolution.batch_digest_mismatch","batch_sha256","drift")

def _plain_json(value:Any)->Any:
    if isinstance(value,Mapping):
        if any(not isinstance(key,str) for key in value):_fail("story_evolution.non_canonical_value","$","JSON object keys must be strings")
        return {key:_plain_json(item) for key,item in value.items()}
    if isinstance(value,Sequence) and not isinstance(value,(str,bytes,bytearray)):return [_plain_json(item) for item in value]
    return value

def _canonical_copy(value:Mapping[str,Any],path:str)->dict[str,Any]:
    try:
        encoded=json.dumps(_plain_json(value),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
        copied=json.loads(encoded)
    except (TypeError,ValueError) as exc:
        _fail("story_evolution.non_canonical_value",path,str(exc))
    if not isinstance(copied,dict):_fail("story_evolution.object_invalid",path,"expected object")
    return copied

def _deadline(value:object,path:str="deadline_at")->datetime:
    text=_text(value,path,64)
    try:parsed=datetime.fromisoformat(text.replace("Z","+00:00"))
    except ValueError as exc:_fail("story_evolution.deadline_invalid",path,"invalid RFC3339 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:_fail("story_evolution.deadline_invalid",path,"timezone required")
    return parsed.astimezone(UTC)

def _normalize_model_output(value:Mapping[str,Any],context:Mapping[str,Any],ir:Mapping[str,Any])->dict[str,Any]:
    """Bind a model proposal body to the frozen context; never commit platform state."""
    raw=_obj(value,"model_output")
    body_fields={"items","dependency_edges","narrative_dependency_refs","warnings","unused_reason"}
    if not body_fields<=set(raw) or set(raw)-body_fields-{"receipt","batch_sha256"}:
        _fail("story_evolution.model_output_fields_invalid","model_output","missing or unknown fields")
    items=list(_seq(raw["items"],"model_output.items"))
    warnings=list(_seq(raw["warnings"],"model_output.warnings"))
    for index,warning in enumerate(warnings):_text(warning,f"model_output.warnings[{index}]",240)
    unused_reason=raw["unused_reason"]
    if items:
        if unused_reason is not None:_fail("story_evolution.receipt_status_invalid","model_output.unused_reason","proposals cannot carry unused reason")
    else:
        unused_reason=_text(unused_reason,"model_output.unused_reason",240)
    p0=sum(isinstance(item,Mapping) and item.get("priority")=="P0" for item in items)
    p1=sum(isinstance(item,Mapping) and item.get("priority")=="P1" for item in items)
    receipt={
        "status":"applied" if items else "no_change","proposal_count":len(items),"p0_count":p0,"p1_count":p1,
        "model_call_count":1,"policy_fingerprint":context["policy"]["policy_fingerprint"],
        "warnings":warnings,"unused_reason":unused_reason,
    }
    if "receipt" in raw and dict(_obj(raw["receipt"],"model_output.receipt"))!=receipt:
        _fail("story_evolution.receipt_mismatch","model_output.receipt","model receipt differs from normalized receipt")
    batch={
        "contract_version":STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA,"operation_ref":context["operation_ref"],
        "base_story_revision":context["base_story_revision"],"base_graph_revision":context["base_graph_revision"],
        "request_fingerprint":context["request_fingerprint"],"policy_fingerprint":context["policy"]["policy_fingerprint"],
        "story_pack_sha256":context["pins"]["story_pack_sha256"],"artifact_sha256":context["pins"]["artifact_sha256"],
        "capability":context["capability"],"items":items,"dependency_edges":list(_seq(raw["dependency_edges"],"model_output.dependency_edges")),
        "narrative_dependency_refs":list(_seq(raw["narrative_dependency_refs"],"model_output.narrative_dependency_refs")),"receipt":receipt,
    }
    batch_sha256=_digest(batch)
    if "batch_sha256" in raw and raw["batch_sha256"]!=batch_sha256:
        _fail("story_evolution.batch_digest_mismatch","model_output.batch_sha256","model digest differs from normalized batch")
    batch["batch_sha256"]=batch_sha256
    validate_evolution_proposal_batch(batch,context,ir)
    return _canonical_copy(batch,"proposal_batch")

class StoryEvolutionGenerationService:
    """Run one structured model call and return only an uncommitted proposal batch."""

    def __init__(
        self,
        *,
        provider_capabilities:Iterable[str],
        definition:Mapping[str,Any]|None=None,
        clock:Callable[[],datetime]|None=None,
        max_output_tokens:int=2048,
        sampling:Mapping[str,Any]|None=None,
    )->None:
        capabilities=frozenset(_ref(item,"provider_capabilities[]") for item in provider_capabilities)
        if not STORY_EVOLUTION_REQUIRED_MODEL_CAPABILITIES<=capabilities:
            _fail("story_evolution.provider_capability_missing","provider_capabilities","structured_output required")
        if isinstance(max_output_tokens,bool) or not isinstance(max_output_tokens,int) or max_output_tokens<1:
            _fail("story_evolution.model_budget_invalid","max_output_tokens","positive integer required")
        self.provider_capabilities=capabilities
        self.definition=None if definition is None else _canonical_copy(definition,"definition")
        self.clock=clock or (lambda:datetime.now(UTC))
        self.max_output_tokens=max_output_tokens
        self.sampling=_canonical_copy(sampling or {"primary_model_calls":1},"sampling")
        if self.sampling!={"primary_model_calls":1}:
            _fail("story_evolution.sampling_invalid","sampling","exactly one primary model call required")
        self._lock=asyncio.Lock()
        self._outcomes:dict[str,dict[str,Any]|StoryEvolutionContractError]={}

    async def generate_story_evolution(
        self,
        context:Mapping[str,Any],
        ir:Mapping[str,Any],
        bridge:PlatformBridge,
        *,
        deadline_at:str,
        definition:Mapping[str,Any]|None=None,
        purpose:ModelPurpose=ModelPurpose.STORY_EVOLUTION,
    )->dict[str,Any]:
        frozen_context=_canonical_copy(_obj(context,"context"),"context")
        frozen_ir=_canonical_copy(_obj(ir,"ir"),"ir")
        active_definition=definition if definition is not None else self.definition
        if active_definition is None:_fail("story_evolution.definition_required","definition","strict IR validation requires its source Definition")
        frozen_definition=_canonical_copy(_obj(active_definition,"definition"),"definition")
        validate_story_evolution_ir(frozen_ir,frozen_definition)
        validate_story_evolution_context(frozen_context,frozen_ir)
        due=_deadline(deadline_at)
        if not isinstance(purpose,ModelPurpose) or purpose is not ModelPurpose.STORY_EVOLUTION:
            _fail("story_evolution.model_purpose_invalid","purpose","STORY_EVOLUTION required")
        fingerprint=frozen_context["request_fingerprint"]
        async with self._lock:
            cached=self._outcomes.get(fingerprint)
            if isinstance(cached,StoryEvolutionContractError):raise cached
            if cached is not None:return cached
            try:
                if self._now()>=due:_fail("story_evolution.deadline_exceeded","deadline_at","expired before model invocation")
                invocation=self._make_invocation(frozen_context,deadline_at,purpose)
                result=await self._invoke_once(bridge,invocation,due)
                self._validate_model_result(result,invocation,due)
                if not isinstance(result.output,Mapping):_fail("story_evolution.model_output_invalid","model_output","structured object required")
                batch=_normalize_model_output(_canonical_copy(result.output,"model_output"),frozen_context,frozen_ir)
            except StoryEvolutionContractError as exc:
                self._outcomes[fingerprint]=exc
                raise
            except Exception as exc:
                error=StoryEvolutionContractError("story_evolution.model_invocation_failed","bridge.invoke_model","provider invocation failed")
                self._outcomes[fingerprint]=error
                raise error from exc
            self._outcomes[fingerprint]=batch
            return batch

    async def generate(self,*args:Any,**kwargs:Any)->dict[str,Any]:
        return await self.generate_story_evolution(*args,**kwargs)

    def _make_invocation(self,context:Mapping[str,Any],deadline_at:str,purpose:ModelPurpose)->ModelInvocationRequest:
        operation_ref=context["operation_ref"]
        fingerprint=context["request_fingerprint"]
        idempotency="model."+hashlib.sha256(f"{operation_ref}|{fingerprint}|1".encode()).hexdigest()[:40]
        system_input=(
            "Return one structured StoryEvolution proposal body only: items, dependency_edges, narrative_dependency_refs, warnings, unused_reason. "
            "Use only frozen context references and local.* proposal refs. Do not assign platform IDs, mutate StoryFlow, commit state, or perform side effects."
        )
        user_input=json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
        return ModelInvocationRequest(operation_ref,1,purpose,system_input,user_input,STORY_EVOLUTION_MODEL_OUTPUT_SCHEMA,self.max_output_tokens,self.sampling,deadline_at,idempotency)

    async def _invoke_once(self,bridge:PlatformBridge,invocation:ModelInvocationRequest,due:datetime)->ModelInvocationResult:
        remaining=(due-self._now()).total_seconds()
        if remaining<=0:_fail("story_evolution.deadline_exceeded","deadline_at","expired before model invocation")
        try:return await asyncio.wait_for(bridge.invoke_model(invocation),timeout=remaining)
        except TimeoutError as exc:raise StoryEvolutionContractError("story_evolution.deadline_exceeded","bridge.invoke_model","model invocation exceeded deadline") from exc

    def _validate_model_result(self,result:object,invocation:ModelInvocationRequest,due:datetime)->None:
        if not isinstance(result,ModelInvocationResult):_fail("story_evolution.model_result_invalid","model_result","ModelInvocationResult required")
        if (result.operation_ref,result.call_sequence)!=(invocation.operation_ref,1):_fail("story_evolution.model_result_correlation_invalid","model_result","operation/call sequence mismatch")
        started=_deadline(result.started_at,"model_result.started_at");completed=_deadline(result.completed_at,"model_result.completed_at")
        if completed<started:_fail("story_evolution.model_result_time_invalid","model_result.completed_at","completed before started")
        if completed>due or self._now()>due:_fail("story_evolution.deadline_exceeded","model_result.completed_at","late result discarded")
        if result.problem is not None:_fail("story_evolution.model_result_problem","model_result.problem","provider returned a problem")
        if result.finish_reason.lower() in {"error","failed","timeout","timed_out","rate_limit","rate_limited"}:_fail("story_evolution.model_result_finish_invalid","model_result.finish_reason","provider did not complete normally")
        if not STORY_EVOLUTION_REQUIRED_MODEL_CAPABILITIES<=result.provider_capabilities:_fail("story_evolution.provider_capability_missing","model_result.provider_capabilities","structured_output required")

    def _now(self)->datetime:
        value=self.clock()
        if not isinstance(value,datetime):_fail("story_evolution.clock_invalid","clock","datetime required")
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)

__all__=["AUTHOR_SOURCE_SCHEMA","STORY_EVOLUTION_DEFINITION_SCHEMA","STORY_EVOLUTION_IR_SCHEMA","STORY_EVOLUTION_CONTEXT_SCHEMA","STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA","STORY_EVOLUTION_MODEL_OUTPUT_SCHEMA","STORY_EVOLUTION_REQUIRED_MODEL_CAPABILITIES","CAPABILITIES","DIRECTIONS","AMPLITUDES","PRIORITY_OBJECT_TYPES","OBJECT_TYPES","BUDGET_FIELDS","StoryEvolutionContractError","StoryEvolutionGenerationService","project_story_evolution_author_source","compile_story_evolution_definition","validate_story_evolution_ir","make_story_evolution_request_fingerprint","validate_story_evolution_context","validate_evolution_proposal_batch"]
