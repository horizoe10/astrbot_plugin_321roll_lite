"""Story-Pack-driven, platform-authoritative character-build contracts."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from .contracts.port import CancellationCheck, OperationEnvelope, PlatformBridge, PortContractError, Problem, ProblemCode, canonical_fingerprint, freeze_json

CHARACTER_BUILD_CAPABILITY="character.build/1.0.0"
CHARACTER_BUILD_AUTHOR_SCHEMA="se-character-build-definitions/1.0.0"
CHARACTER_BUILD_AUTHOR_SCHEMA_V11="se-character-build-definitions/1.1.0"
CHARACTER_BUILD_AUTHOR_SCHEMA_V12="se-character-build-definitions/1.2.0"
CHARACTER_BUILD_SNAPSHOT_SCHEMA="se-character-build-draft-snapshot/1.0.0"
CHARACTER_BUILD_REQUEST_SCHEMA="se-character-build-evaluation/1.0.0"
CHARACTER_BUILD_PROPOSAL_SCHEMA="se-character-build-proposal/1.0.0"
CHARACTER_BUILD_RESULT_SCHEMA="se-character-build-result/1.0.0"
_MODES=frozenset({"preset","step_choices","point_buy","platform_random","hybrid"})
_STEP_METHODS=frozenset({"choice","point_buy","platform_random"})
_STEP_METHODS_V11=frozenset({"choice","player_text","computed_checkpoint"})

class CharacterBuildContractError(ValueError):
    def __init__(self,code,path,reason): self.code,self.path,self.reason=code,path,reason; super().__init__(f"{code}:{path}")
def _fail(code,path,reason): raise CharacterBuildContractError(code,path,reason)
def _text(v,p,n=240):
    if not isinstance(v,str) or not v.strip() or len(v)>n:_fail("character_build.text_invalid",p,"必须是有界非空文本。")
    return v.strip()
def _ref(v,p):
    r=_text(v,p,128)
    if not r[0].isalnum() or any(not(c.isalnum() or c in "_.:@-") for c in r):_fail("character_build.ref_invalid",p,"必须是 opaque ref。")
    return r
def _hash(v,p):
    r=_text(v,p,71)
    if len(r)!=71 or not r.startswith("sha256:") or any(c not in "0123456789abcdef" for c in r[7:]):_fail("character_build.hash_invalid",p,"必须是 SHA-256。")
    return r
def _seq(v,p):
    if not isinstance(v,Sequence) or isinstance(v,(str,bytes,bytearray)):_fail("character_build.array_invalid",p,"必须是数组。")
    return v
def _map(v,p):
    if not isinstance(v,Mapping):_fail("character_build.object_invalid",p,"必须是对象。")
    return v
def _plain(v):
    if isinstance(v,Mapping):return {str(k):_plain(x) for k,x in v.items()}
    if isinstance(v,Sequence) and not isinstance(v,(str,bytes,bytearray)):return [_plain(x) for x in v]
    return v

def _compile_character_build_definitions_v11(document:Mapping[str,Any],candidate_catalog_document:Mapping[str,Any]|None,selection_rules=None)->dict[str,Any]:
    if set(document)!={"schema","recipes","legacy_recipes","non_recipe_actions"}:_fail("character_build.document_invalid","$","1.1 作者文档字段无效。")
    if document.get("schema")!=CHARACTER_BUILD_AUTHOR_SCHEMA_V11:_fail("character_build.document_invalid","schema","1.1 作者文档 identity 无效。")
    if list(document.get("non_recipe_actions",())) != ["display_name","character_overview","final_confirmation","atomic_creation"]:_fail("character_build.non_recipe_actions_invalid","non_recipe_actions","名称、总览、确认和创建必须位于 recipe 外。")
    if not isinstance(document.get("legacy_recipes"),Sequence) or isinstance(document.get("legacy_recipes"),(str,bytes,bytearray)):_fail("character_build.legacy_recipes_invalid","legacy_recipes","旧 recipe 只能作为数组证据保留。")
    if not isinstance(candidate_catalog_document,Mapping) or candidate_catalog_document.get("schema")!="sp-character-builds/3":_fail("character_build.candidate_catalog_invalid","candidate_catalog_document","1.1 recipe requires the exact Story Pack candidate catalog.")
    resolved_raw=candidate_catalog_document.get("resolved_candidate_catalogs")
    resolved={}
    candidate_fields={"selection_ref","source_ref","display_name","summary","detail","rule_effects","limitations_and_risks","requires_source_refs","excludes_source_refs","resolver_metadata"}
    for i,catalog_raw in enumerate(_seq(resolved_raw,"resolved_candidate_catalogs")):
        catalog=_map(catalog_raw,f"resolved_candidate_catalogs[{i}]")
        if set(catalog)!={"candidate_map_ref","candidates"}:_fail("character_build.candidate_catalog_invalid",f"resolved_candidate_catalogs[{i}]","candidate map fields invalid.")
        map_ref=_ref(catalog["candidate_map_ref"],f"resolved_candidate_catalogs[{i}].candidate_map_ref")
        if map_ref in resolved:_fail("character_build.candidate_map_duplicate",f"resolved_candidate_catalogs[{i}]","candidate_map_ref duplicate.")
        candidates=[];seen_selections=set();seen_sources=set()
        for j,candidate_raw in enumerate(_seq(catalog["candidates"],f"resolved_candidate_catalogs[{i}].candidates")):
            candidate=_map(candidate_raw,f"resolved_candidate_catalogs[{i}].candidates[{j}]")
            if set(candidate)!=candidate_fields:_fail("character_build.candidate_invalid",f"resolved_candidate_catalogs[{i}].candidates[{j}]","resolved candidate fields invalid.")
            selection_ref=_ref(candidate["selection_ref"],f"resolved_candidate_catalogs[{i}].candidates[{j}].selection_ref")
            source_ref=_ref(candidate["source_ref"],f"resolved_candidate_catalogs[{i}].candidates[{j}].source_ref")
            if selection_ref in seen_selections or (source_ref in seen_sources and (selection_rules is None or source_ref not in selection_rules['variants'])):_fail("character_build.candidate_duplicate",f"resolved_candidate_catalogs[{i}].candidates[{j}]","selection/source identity duplicate in map.")
            seen_selections.add(selection_ref);seen_sources.add(source_ref)
            for key in ("display_name","summary","detail"):_text(candidate[key],f"resolved_candidate_catalogs[{i}].candidates[{j}].{key}",4000)
            for key in ("rule_effects","limitations_and_risks","requires_source_refs","excludes_source_refs"):
                values=list(_seq(candidate[key],f"resolved_candidate_catalogs[{i}].candidates[{j}].{key}"))
                if any(not isinstance(value,str) or not value for value in values):_fail("character_build.candidate_invalid",f"resolved_candidate_catalogs[{i}].candidates[{j}].{key}","candidate list values invalid.")
            _map(candidate["resolver_metadata"],f"resolved_candidate_catalogs[{i}].candidates[{j}].resolver_metadata")
            candidates.append(_plain(candidate))
        if not candidates:_fail("character_build.candidate_catalog_empty",f"resolved_candidate_catalogs[{i}]","candidate map must not be empty.")
        resolved[map_ref]=candidates
    if len(resolved)!=28:_fail("character_build.candidate_map_closure_invalid","resolved_candidate_catalogs","exactly 28 resolved maps are required.")
    recipes=[];seen=set();used_maps=set();global_selections=set()
    recipe_fields={"recipe_ref","replaces_recipe_ref","label","modes","steps","counts","preview_fields","allow_back","allow_reset","allow_pause_resume","final_self_confirmation_required","completion_contract","dependency_policy","runtime_policy"}
    base_step={"ordinal","step_ref","label","question","depends_on","produces","method","input_mode","minimum","maximum"}
    method_fields={
        "player_text":{"text_contract"},
        "computed_checkpoint":{"computation_ref","accepts_player_input","llm_calls","outputs"},
        "choice":{"candidate_map_ref","optional","selection_policy","value_bonus","excludes_selected_from","selection_slot","skip_action_ref"},
    }
    for i,raw in enumerate(_seq(document["recipes"],"recipes")):
        p=f"recipes[{i}]";v=_map(raw,p)
        if set(v)!=recipe_fields:_fail("character_build.recipe_fields_invalid",p,"1.1 recipe 字段缺失或未知。")
        ref=_ref(v["recipe_ref"],p+".recipe_ref")
        if ref in seen:_fail("character_build.recipe_duplicate",p,"recipe_ref 重复。")
        seen.add(ref);_ref(v["replaces_recipe_ref"],p+".replaces_recipe_ref");_text(v["label"],p+".label")
        if list(v["modes"]) != ["sequential_messages","step_choices"]:_fail("character_build.modes_invalid",p+".modes","1.1 连续建卡必须声明消息序列与 step_choices。")
        steps=[];step_refs=[]
        for j,item_raw in enumerate(_seq(v["steps"],p+".steps")):
            sp=f"{p}.steps[{j}]";item=_map(item_raw,sp);method=str(item.get("method"))
            if method not in _STEP_METHODS_V11 or set(item)-base_step-method_fields[method]:_fail("character_build.step_invalid",sp,"1.1 step 字段或 method 无效。")
            required=base_step | ({"candidate_map_ref","optional","selection_policy"} if method=="choice" else method_fields[method])
            if not required<=set(item):_fail("character_build.step_invalid",sp,"1.1 step 缺少 method 必需字段。")
            ordinal=item["ordinal"]
            if isinstance(ordinal,bool) or ordinal!=j+1:_fail("character_build.step_order_invalid",sp,"ordinal 必须连续。")
            step_ref=_ref(item["step_ref"],sp+".step_ref")
            if step_ref in step_refs:_fail("character_build.step_duplicate",sp,"step_ref 重复。")
            step_refs.append(step_ref);_text(item["label"],sp+".label");_text(item["question"],sp+".question",800)
            for key in ("depends_on","produces"):
                refs=[_ref(x,sp+"."+key) for x in _seq(item[key],sp+"."+key)]
                if len(refs)!=len(set(refs)):_fail("character_build.step_dependency_invalid",sp+"."+key,"引用必须唯一。")
            minimum,maximum=item["minimum"],item["maximum"]
            if any(isinstance(x,bool) or not isinstance(x,int) for x in (minimum,maximum)) or not 0<=minimum<=maximum<=1:_fail("character_build.cardinality_invalid",sp,"1.1 step cardinality 无效。")
            if item.get("input_mode")!=method:_fail("character_build.input_mode_invalid",sp,"input_mode 必须等于 method。")
            if method=="player_text":
                tc=_map(item["text_contract"],sp+".text_contract")
                if set(tc)!={"minimum_characters","maximum_characters","allow_empty","normalization","reject_control_characters","reject_dangerous_injection_markers","store_original","visibility"} or tc["allow_empty"] is not False or tc["reject_control_characters"] is not True:_fail("character_build.text_contract_invalid",sp,"player_text 合同不闭合。")
            elif method=="computed_checkpoint":
                if item["accepts_player_input"] is not False or item["llm_calls"]!=0 or minimum!=0 or maximum!=0:_fail("character_build.checkpoint_invalid",sp,"computed checkpoint 必须零输入、零 LLM。")
                _ref(item["computation_ref"],sp+".computation_ref")
            else:
                map_ref=_ref(item["candidate_map_ref"],sp+".candidate_map_ref")
                if map_ref in used_maps or map_ref not in resolved:_fail("character_build.candidate_map_closure_invalid",sp+".candidate_map_ref","choice map missing, unknown, or reused.")
                used_maps.add(map_ref)
                selections={candidate["selection_ref"] for candidate in resolved[map_ref]}
                if global_selections & selections:_fail("character_build.candidate_duplicate",sp+".candidate_map_ref","selection_ref must be globally unique.")
                global_selections.update(selections)
                if not isinstance(item["optional"],bool) or item["selection_policy"]!="explicit_no_default":_fail("character_build.choice_policy_invalid",sp,"choice 必须显式且无默认。")
                if item["optional"]!=(minimum==0) or (item["optional"] and item.get("skip_action_ref")!="build.action.skip_current_step"):_fail("character_build.skip_contract_invalid",sp,"可选 choice 必须显式提供 skip。")
            compiled_item=_plain(item)
            if method=="choice":compiled_item["candidates"]=resolved[compiled_item["candidate_map_ref"]]
            steps.append(compiled_item)
        if len(steps)!=30 or [x["method"] for x in steps].count("player_text")!=1 or [x["method"] for x in steps].count("computed_checkpoint")!=1 or steps[0]["method"]!="player_text" or steps[14]["method"]!="computed_checkpoint":_fail("character_build.thirty_node_contract_invalid",p,"必须是冻结的 30 节点结构。")
        if any(dep not in step_refs[:index] for index,item in enumerate(steps) for dep in item["depends_on"]):_fail("character_build.step_dependency_invalid",p,"depends_on 只能指向先前节点。")
        counts=v["counts"]
        expected_counts={"nodes":30,"answer_steps":29,"player_text_steps":1,"choice_steps":28,"computed_checkpoint_steps":1,"optional_choice_steps":4}
        if counts!=expected_counts:_fail("character_build.counts_invalid",p,"1.1 counts 与冻结结构不符。")
        if v["final_self_confirmation_required"] is not True or v["completion_contract"].get("terminal_state")!="ready_to_confirm" or v["completion_contract"].get("confirmation_is_recipe_step") is not False:_fail("character_build.authority_invalid",p,"确认必须位于 recipe 外并绑定 ready_to_confirm。")
        material={"schema":"se-character-build-recipe-ir/1.1.0",**{key:_plain(v[key]) for key in recipe_fields}}
        if selection_rules is not None:material.update(schema='se-character-build-recipe-ir/1.2.0',selection_rules=_plain(selection_rules))
        material["steps"]=steps
        material["recipe_sha256"]=canonical_fingerprint(material);recipes.append(material)
    if used_maps!=set(resolved):_fail("character_build.candidate_map_closure_invalid","resolved_candidate_catalogs","resolved maps and recipe choice maps differ.")
    catalog={"schema":"se-character-build-catalog-ir/1.2.0" if selection_rules is not None else "se-character-build-catalog-ir/1.1.0","recipes":sorted(recipes,key=lambda x:x["recipe_ref"]),"non_recipe_actions":list(document["non_recipe_actions"]),"candidate_catalog_schema":"sp-character-builds/3"};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog

def compile_character_build_definitions(document:Mapping[str,Any],candidate_catalog_document:Mapping[str,Any]|None=None)->dict[str,Any]:
    if isinstance(document,Mapping) and document.get('schema')==CHARACTER_BUILD_AUTHOR_SCHEMA_V12:
        from .character_build_selection import validate_selection_rules,SelectionRuleError
        if set(document)!={'schema','recipes','legacy_recipes','non_recipe_actions','selection_rules'} or not isinstance(candidate_catalog_document,Mapping):_fail('character_build.selection_rules_invalid','$','1.2 selection rules and resolved catalog are required.')
        try:rules=validate_selection_rules(document['selection_rules'],candidate_catalog_document['resolved_candidate_catalogs'])
        except (SelectionRuleError,KeyError,TypeError):_fail('character_build.selection_rules_invalid','selection_rules','Variant identities, prerequisite graph or required skills are invalid.')
        legacy={key:value for key,value in document.items() if key!='selection_rules'};legacy['schema']=CHARACTER_BUILD_AUTHOR_SCHEMA_V11
        return _compile_character_build_definitions_v11(legacy,candidate_catalog_document,rules)
    if isinstance(document,Mapping) and document.get("schema")==CHARACTER_BUILD_AUTHOR_SCHEMA_V11:return _compile_character_build_definitions_v11(document,candidate_catalog_document)
    if candidate_catalog_document is not None:_fail("character_build.candidate_catalog_invalid","candidate_catalog_document","legacy recipe does not accept the 0.2 candidate catalog.")
    if set(document)!={"schema","recipes"} or document.get("schema")!=CHARACTER_BUILD_AUTHOR_SCHEMA:_fail("character_build.document_invalid","$","作者文档版本或字段无效。")
    if not document["recipes"]:_fail("character_build.recipes_empty","recipes","至少需要一个 recipe。")
    recipes=[]; seen=set()
    for i,raw in enumerate(_seq(document["recipes"],"recipes")):
        p=f"recipes[{i}]"; v=_map(raw,p)
        fields={"recipe_ref","label","modes","presets","steps","point_budgets","preview_fields","allow_back","allow_reset","allow_pause_resume","final_self_confirmation_required"}
        if set(v)!=fields:_fail("character_build.recipe_fields_invalid",p,"recipe 字段缺失或未知。")
        ref=_ref(v["recipe_ref"],p+".recipe_ref")
        if ref in seen:_fail("character_build.recipe_duplicate",p,"recipe_ref 重复。")
        seen.add(ref); modes=tuple(_ref(x,p+".modes") for x in _seq(v["modes"],p+".modes"))
        if not modes or len(modes)!=len(set(modes)) or not set(modes)<=_MODES:_fail("character_build.modes_invalid",p+".modes","建角模式无效。")
        presets=[]; preset_refs=set()
        for j,item in enumerate(_seq(v["presets"],p+".presets")):
            item=_map(item,f"{p}.presets[{j}]")
            if set(item)!={"preset_ref","label","values"}:_fail("character_build.preset_invalid",p,"preset 字段无效。")
            pr=_ref(item["preset_ref"],p)
            if pr in preset_refs:_fail("character_build.preset_duplicate",p,"preset_ref 重复。")
            preset_refs.add(pr); presets.append({"preset_ref":pr,"label":_text(item["label"],p),"values":_plain(_map(item["values"],p))})
        candidates={}; steps=[]; step_refs=[]
        for j,item in enumerate(_seq(v["steps"],p+".steps")):
            item=_map(item,f"{p}.steps[{j}]")
            if set(item)!={"step_ref","label","method","candidates","minimum","maximum","budget_ref","random_table_ref"}:_fail("character_build.step_invalid",p,"step 字段无效。")
            sr=_ref(item["step_ref"],p); method=str(item["method"])
            if sr in step_refs or method not in _STEP_METHODS:_fail("character_build.step_invalid",p,"step ref/method 无效。")
            minimum,maximum=item["minimum"],item["maximum"]
            if any(isinstance(x,bool) or not isinstance(x,int) for x in (minimum,maximum)) or not 0<=minimum<=maximum<=32:_fail("character_build.cardinality_invalid",p,"step cardinality 无效。")
            cs=[]
            for k,c in enumerate(_seq(item["candidates"],p)):
                c=_map(c,p)
                if set(c)!={"candidate_ref","label","cost","requires","excludes"}:_fail("character_build.candidate_invalid",p,"candidate 字段无效。")
                cr=_ref(c["candidate_ref"],p)
                if cr in candidates:_fail("character_build.candidate_duplicate",p,"candidate_ref 重复。")
                cost=c["cost"]
                if isinstance(cost,bool) or not isinstance(cost,int) or cost<0:_fail("character_build.cost_invalid",p,"cost 无效。")
                requires=[_ref(x,p) for x in _seq(c["requires"],p)];excludes=[_ref(x,p) for x in _seq(c["excludes"],p)]
                if len(requires)!=len(set(requires)) or len(excludes)!=len(set(excludes)) or set(requires)&set(excludes) or cr in requires or cr in excludes:_fail("character_build.candidate_relation_invalid",p,"requires/excludes 必须唯一、互斥且不可自引用。")
                candidates[cr]=sr; cs.append({"candidate_ref":cr,"label":_text(c["label"],p),"cost":cost,"requires":requires,"excludes":excludes})
            budget_ref=None if item["budget_ref"] is None else _ref(item["budget_ref"],p); random_ref=None if item["random_table_ref"] is None else _ref(item["random_table_ref"],p)
            if method=="point_buy" and budget_ref is None or method=="platform_random" and random_ref is None:_fail("character_build.step_dependency_missing",p,"点购/随机 step 缺少依赖 ref。")
            if method!="point_buy" and budget_ref is not None or method!="platform_random" and random_ref is not None:_fail("character_build.step_dependency_invalid",p,"只有对应 step method 可携带 budget/random table。")
            steps.append({"step_ref":sr,"label":_text(item["label"],p),"method":method,"candidates":cs,"minimum":minimum,"maximum":maximum,"budget_ref":budget_ref,"random_table_ref":random_ref}); step_refs.append(sr)
            if maximum>len(cs) or minimum>len(cs):_fail("character_build.cardinality_impossible",p,"step cardinality 超过候选数量。")
        budgets=[]; budget_refs=set()
        for item in _seq(v["point_budgets"],p):
            item=_map(item,p)
            if set(item)!={"budget_ref","total"}:_fail("character_build.budget_invalid",p,"budget 字段无效。")
            br=_ref(item["budget_ref"],p); total=item["total"]
            if br in budget_refs or isinstance(total,bool) or not isinstance(total,int) or total<0:_fail("character_build.budget_invalid",p,"budget 无效。")
            budget_refs.add(br); budgets.append({"budget_ref":br,"total":total})
        if any(s["budget_ref"] not in budget_refs for s in steps if s["budget_ref"]):_fail("character_build.budget_unknown",p,"step 引用未知 budget。")
        if budget_refs!={s["budget_ref"] for s in steps if s["method"]=="point_buy"}:_fail("character_build.budget_unused",p,"point budget 必须被唯一语义步骤引用且不得多余。")
        if any(ref not in candidates for step in steps for c in step["candidates"] for ref in (*c["requires"],*c["excludes"])):_fail("character_build.candidate_relation_unknown",p,"requires/excludes 引用未知 candidate。")
        for preset in presets:
            if set(preset["values"]) - set(step_refs) or any(value not in candidates or candidates[value]!=step for step,value in preset["values"].items()):_fail("character_build.preset_values_invalid",p,"preset values 必须按 step_ref 指向该步骤候选。")
            selected=set(preset["values"].values())
            if any(any(req not in selected for req in next(c for c in step["candidates"] if c["candidate_ref"]==ref)["requires"]) or any(exc in selected for exc in next(c for c in step["candidates"] if c["candidate_ref"]==ref)["excludes"]) for step_ref,ref in preset["values"].items() for step in steps if step["step_ref"]==step_ref):_fail("character_build.preset_relations_invalid",p,"preset 违反 requires/excludes。")
            for step in steps:
                if step["method"]=="platform_random":continue
                count=sum(1 for ref in selected if candidates.get(ref)==step["step_ref"])
                if not step["minimum"]<=count<=step["maximum"]:_fail("character_build.preset_incomplete",p,"preset 未满足非随机 step cardinality。")
            for budget in budgets:
                spent=sum(next(c for c in step["candidates"] if c["candidate_ref"]==ref)["cost"] for ref in selected for step in steps if step["budget_ref"]==budget["budget_ref"] and candidates.get(ref)==step["step_ref"])
                if spent>budget["total"]:_fail("character_build.preset_budget_invalid",p,"preset 超过 point budget。")
        if ("preset" in modes)!=(bool(presets)):_fail("character_build.preset_mode_invalid",p,"preset mode 与 presets 不一致。")
        method_modes={"choice":"step_choices","point_buy":"point_buy","platform_random":"platform_random"};present_methods={x["method"] for x in steps}
        if any((mode in modes)!=(method in present_methods) for method,mode in method_modes.items()) or ("hybrid" in modes and len(present_methods|({"preset"} if presets else set()))<2):_fail("character_build.mode_method_mismatch",p,"modes 与 step methods 不一致。")
        if v["final_self_confirmation_required"] is not True or not all(isinstance(v[x],bool) for x in ("allow_back","allow_reset","allow_pause_resume")):_fail("character_build.authority_invalid",p,"最终本人确认必须开启且恢复开关必须为布尔值。")
        preview_fields=[_ref(x,p) for x in _seq(v["preview_fields"],p)]
        if len(preview_fields)!=len(set(preview_fields)) or not set(preview_fields)<=set(step_refs):_fail("character_build.preview_fields_invalid",p,"preview_fields 必须是唯一已注册 step refs。")
        material={"schema":"se-character-build-recipe-ir/1.0.0","recipe_ref":ref,"label":_text(v["label"],p),"modes":list(modes),"presets":presets,"steps":steps,"point_budgets":budgets,"preview_fields":preview_fields,"allow_back":v["allow_back"],"allow_reset":v["allow_reset"],"allow_pause_resume":v["allow_pause_resume"],"final_self_confirmation_required":True}
        material["recipe_sha256"]=canonical_fingerprint(material);recipes.append(material)
    catalog={"schema":"se-character-build-catalog-ir/1.0.0","recipes":sorted(recipes,key=lambda x:x["recipe_ref"])};catalog["catalog_sha256"]=canonical_fingerprint(catalog);return catalog

def bind_character_build(extension,catalog):
    if set(extension)!={"recipe_ref"}:_fail("character_build.extension_invalid","extensions.character.build/1.0.0","extension 只能包含 recipe_ref。")
    ref=_ref(extension["recipe_ref"],"recipe_ref"); recipe=next((x for x in catalog["recipes"] if x["recipe_ref"]==ref),None)
    if recipe is None:_fail("character_build.recipe_unknown","recipe_ref","recipe 未注册。")
    return {"schema":"se-character-build-binding-ir/1.0.0","recipe_ref":ref,"recipe_sha256":recipe["recipe_sha256"]}

@dataclass(frozen=True,slots=True)
class CharacterBuildDraftSnapshot:
    schema:str; draft_ref:str; draft_revision:int; recipe_ref:str; recipe_sha256:str; owner_ref:str; slot_ref:str; current_step_ref:str|None
    selected_refs:tuple[str,...]; allocations:Mapping[str,int]; random_receipts:Mapping[str,str]; paused:bool; final_self_confirmed:bool; expected_session_revision:int; fingerprint:str
    def __post_init__(self):
        if self.schema!=CHARACTER_BUILD_SNAPSHOT_SCHEMA:raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"build_snapshot","schema 无效。")
        for n in ("draft_ref","recipe_ref","owner_ref","slot_ref"):_ref(getattr(self,n),n)
        _hash(self.recipe_sha256,"recipe_sha256");_hash(self.fingerprint,"fingerprint")
        if self.current_step_ref is not None:_ref(self.current_step_ref,"current_step_ref")
        if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.draft_revision,self.expected_session_revision)) or not isinstance(self.paused,bool) or not isinstance(self.final_self_confirmed,bool):raise PortContractError(ProblemCode.INPUT_INVALID,"build_snapshot","revision/boolean 无效。")
        if not isinstance(self.selected_refs,tuple) or len(self.selected_refs)!=len(set(self.selected_refs)) or not isinstance(self.random_receipts,Mapping) or len(self.random_receipts.values())!=len(set(self.random_receipts.values())):raise PortContractError(ProblemCode.INPUT_INVALID,"build_snapshot","selection/random receipts 必须唯一。")
        for value in self.selected_refs:_ref(value,"selected_refs")
        for step_ref,receipt_ref in self.random_receipts.items():_ref(step_ref,"random_receipts.step_ref");_ref(receipt_ref,"random_receipts.receipt_ref")
        if not isinstance(self.allocations,Mapping) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in self.allocations.items()):raise PortContractError(ProblemCode.INPUT_INVALID,"allocations","allocation 必须是非负整数映射。")
        object.__setattr__(self,"allocations",freeze_json(self.allocations,"allocations"));object.__setattr__(self,"random_receipts",freeze_json(self.random_receipts,"random_receipts"))
    def to_mapping(self):return {**{n:getattr(self,n) for n in self.__dataclass_fields__},"selected_refs":list(self.selected_refs),"random_receipts":_plain(self.random_receipts),"allocations":_plain(self.allocations)}
    def material(self):return {k:v for k,v in self.to_mapping().items() if k!="fingerprint"}
def character_build_snapshot_fingerprint(x):return canonical_fingerprint(x.material())

class CharacterBuildAction(StrEnum): PREVIEW="preview"; APPLY_PRESET="apply_preset"; CHOOSE="choose"; ALLOCATE="allocate"; REQUEST_RANDOM="request_random"; APPLY_RANDOM_RECEIPT="apply_random_receipt"; BACK="back"; RESET="reset"; PAUSE="pause"; RESUME="resume"; CONFIRM="confirm"
@dataclass(frozen=True,slots=True)
class CharacterBuildRequest:
    schema:str; envelope:OperationEnvelope; action:CharacterBuildAction; snapshot:CharacterBuildDraftSnapshot; input:Mapping[str,Any]
    def __post_init__(self):
        if self.schema!=CHARACTER_BUILD_REQUEST_SCHEMA or self.envelope.operation_type!="evaluate_character_build" or self.envelope.expected_revision!=self.snapshot.expected_session_revision or not isinstance(self.action,CharacterBuildAction) or not isinstance(self.input,Mapping):raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE,"build_request","请求 schema/action/input/operation/revision 无效。")
        object.__setattr__(self,"input",freeze_json(self.input,"build_input"))
def character_build_request_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"envelope":{n:getattr(x.envelope,n) for n in x.envelope.__dataclass_fields__ if n!="request_fingerprint"},"action":x.action.value,"snapshot_fingerprint":x.snapshot.fingerprint,"input":_plain(x.input)})
def decode_character_build_snapshot(value):
    v=freeze_json(value,"build_snapshot")
    if set(v)!=set(CharacterBuildDraftSnapshot.__dataclass_fields__) or not isinstance(v["selected_refs"],tuple) or not isinstance(v["random_receipts"],Mapping):raise ValueError("build snapshot fields/types invalid")
    d=dict(v);d["selected_refs"]=tuple(d["selected_refs"]);return CharacterBuildDraftSnapshot(**d)
def decode_character_build_request(value):
    v=freeze_json(value,"build_request")
    if set(v)!={"schema","envelope","action","snapshot","input"} or not all(isinstance(v[x],Mapping) for x in ("envelope","snapshot","input")):raise ValueError("build request fields invalid")
    return CharacterBuildRequest(str(v["schema"]),OperationEnvelope(**dict(v["envelope"])),CharacterBuildAction(str(v["action"])),decode_character_build_snapshot(v["snapshot"]),v["input"])

class CharacterBuildProposalKind(StrEnum): PREVIEW="preview"; DRAFT_PATCH="draft_patch"; RANDOM_REQUEST="random_request"; VALIDATION="validation"; CREATE_CANDIDATE="create_candidate"; PAUSE="pause"
class CharacterBuildStatus(StrEnum): PROPOSED="proposed"; INVALID="invalid"; BLOCKED="blocked"; CANCELLED="cancelled"; TIMED_OUT="timed_out"
@dataclass(frozen=True,slots=True)
class CharacterBuildProposal:
    schema:str; proposal_ref:str; operation_ref:str; source_draft_revision:int; kind:CharacterBuildProposalKind; public_preview:Mapping[str,Any]; private_draft_patch:Mapping[str,Any]|None; validation_errors:tuple[str,...]; requires_platform_commit:bool=True; creates_actor:bool=False
    def __post_init__(self):
        if self.schema!=CHARACTER_BUILD_PROPOSAL_SCHEMA or self.creates_actor is not False or self.requires_platform_commit is not True:raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_proposal","proposal authority 无效。")
        _ref(self.proposal_ref,"proposal_ref");_ref(self.operation_ref,"operation_ref")
        if isinstance(self.source_draft_revision,bool) or not isinstance(self.source_draft_revision,int) or self.source_draft_revision<0 or not isinstance(self.validation_errors,tuple) or any(not isinstance(x,str) for x in self.validation_errors):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_proposal","proposal fields 无效。")
        if self.kind in {CharacterBuildProposalKind.PREVIEW,CharacterBuildProposalKind.VALIDATION} and self.private_draft_patch is not None or self.kind in {CharacterBuildProposalKind.DRAFT_PATCH,CharacterBuildProposalKind.RANDOM_REQUEST,CharacterBuildProposalKind.CREATE_CANDIDATE,CharacterBuildProposalKind.PAUSE} and self.private_draft_patch is None:raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_proposal","kind/private patch cross-field invalid。")
        object.__setattr__(self,"public_preview",freeze_json(self.public_preview,"public_preview"));object.__setattr__(self,"private_draft_patch",None if self.private_draft_patch is None else freeze_json(self.private_draft_patch,"private_draft_patch"))
@dataclass(frozen=True,slots=True)
class CharacterBuildResult:
    schema:str; operation_ref:str; request_fingerprint:str; expected_revision:int; source_draft_revision:int; status:CharacterBuildStatus; proposal:CharacterBuildProposal|None=None; problems:tuple[Problem,...]=(); result_fingerprint:str="sha256:"+"0"*64
    def __post_init__(self):
        if self.schema!=CHARACTER_BUILD_RESULT_SCHEMA or not isinstance(self.problems,tuple):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","result schema/types 无效。")
        if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.expected_revision,self.source_draft_revision)):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","result revision 无效。")
        if self.proposal is not None and (self.proposal.operation_ref!=self.operation_ref or self.proposal.source_draft_revision!=self.source_draft_revision):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","proposal/result identity mismatch。")
        if self.status in {CharacterBuildStatus.PROPOSED,CharacterBuildStatus.INVALID} and (self.proposal is None or self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","proposal status cross-field invalid。")
        if self.status is CharacterBuildStatus.INVALID and self.proposal is not None and self.proposal.kind is not CharacterBuildProposalKind.VALIDATION or self.status is CharacterBuildStatus.PROPOSED and self.proposal is not None and self.proposal.kind is CharacterBuildProposalKind.VALIDATION:raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","status/proposal kind mismatch。")
        if self.status in {CharacterBuildStatus.BLOCKED,CharacterBuildStatus.CANCELLED,CharacterBuildStatus.TIMED_OUT} and (self.proposal is not None or not self.problems):raise PortContractError(ProblemCode.OUTPUT_INVALID,"build_result","terminal status cross-field invalid。")
def character_build_result_fingerprint(x):return canonical_fingerprint({"schema":x.schema,"operation_ref":x.operation_ref,"request_fingerprint":x.request_fingerprint,"expected_revision":x.expected_revision,"source_draft_revision":x.source_draft_revision,"status":x.status.value,"proposal":None if x.proposal is None else _plain({n:(getattr(x.proposal,n).value if isinstance(getattr(x.proposal,n),StrEnum) else getattr(x.proposal,n)) for n in x.proposal.__dataclass_fields__}),"problems":[{n:(getattr(p,n).value if isinstance(getattr(p,n),StrEnum) else getattr(p,n)) for n in p.__dataclass_fields__} for p in x.problems]})
def decode_character_build_result(value):
    v=freeze_json(value,"build_result")
    if set(v)!=set(CharacterBuildResult.__dataclass_fields__):raise ValueError("build result fields invalid")
    p=v["proposal"];proposal=None
    if p is not None:
        if not isinstance(p,Mapping) or set(p)!=set(CharacterBuildProposal.__dataclass_fields__) or not isinstance(p["validation_errors"],tuple):raise ValueError("build proposal fields invalid")
        proposal=CharacterBuildProposal(str(p["schema"]),str(p["proposal_ref"]),str(p["operation_ref"]),p["source_draft_revision"],CharacterBuildProposalKind(str(p["kind"])),p["public_preview"],p["private_draft_patch"],tuple(p["validation_errors"]),p["requires_platform_commit"],p["creates_actor"])
    if not isinstance(v["problems"],tuple):raise ValueError("problems must array")
    problems=[]
    for x in v["problems"]:
        if not isinstance(x,Mapping) or set(x)!=set(Problem.__dataclass_fields__):raise ValueError("problem invalid")
        problems.append(Problem(ProblemCode(str(x["code"])),str(x["failed_operation"]),str(x["reason"]),str(x["automatic_handling"]),str(x["next_action"]),x["retryable"]))
    r=CharacterBuildResult(str(v["schema"]),str(v["operation_ref"]),str(v["request_fingerprint"]),v["expected_revision"],v["source_draft_revision"],CharacterBuildStatus(str(v["status"])),proposal,tuple(problems),str(v["result_fingerprint"]))
    if r.result_fingerprint!=character_build_result_fingerprint(r):raise PortContractError(ProblemCode.RESULT_STALE,"result_fingerprint","result fingerprint mismatch")
    return r

class CharacterBuildEvaluator:
    def __init__(self,artifact):
        c=artifact.get("character_build_definitions")
        if not isinstance(c,Mapping) or c.get("catalog_sha256")!=canonical_fingerprint({k:v for k,v in c.items() if k!="catalog_sha256"}):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"character_build_definitions","catalog 缺失或损坏。")
        recipes={}
        for x in c["recipes"]:
            if x.get("recipe_sha256")!=canonical_fingerprint({k:v for k,v in x.items() if k!="recipe_sha256"}) or x["recipe_ref"] in recipes:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"character_build_recipe","recipe hash/identity 损坏。")
            recipes[x["recipe_ref"]]=freeze_json(x,"recipe")
        for event in artifact.get("event_compositions",()):
            b=event.get("character_build")
            if b is not None and (not isinstance(b,Mapping) or b.get("recipe_ref") not in recipes or b.get("recipe_sha256")!=recipes[b["recipe_ref"]]["recipe_sha256"]):raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,"character_build_binding","event binding 损坏。")
        self.recipes=MappingProxyType(recipes)
    def evaluate(self,r):
        s=r.snapshot
        if r.envelope.request_fingerprint!=character_build_request_fingerprint(r) or s.fingerprint!=character_build_snapshot_fingerprint(s):return self._blocked(r,ProblemCode.RESULT_STALE,"request/snapshot fingerprint stale")
        recipe=self.recipes.get(s.recipe_ref)
        if recipe is None or recipe["recipe_sha256"]!=s.recipe_sha256:return self._blocked(r,ProblemCode.CONTRACT_INCOMPATIBLE,"recipe identity mismatch")
        if recipe.get("schema") in ("se-character-build-recipe-ir/1.1.0","se-character-build-recipe-ir/1.2.0"):
            step=next((item for item in recipe["steps"] if item["step_ref"]==s.current_step_ref),None)
            public={"recipe_label":recipe["label"],"current_step":None if step is None else step["label"],"current_step_method":None if step is None else step["method"],"selected_count":len(s.selected_refs),"paused":s.paused,"ready_to_confirm":s.current_step_ref is None}
            if r.action is CharacterBuildAction.PREVIEW and not r.input:
                return self._proposal(r,CharacterBuildProposalKind.PREVIEW,public,None,())
            return self._blocked(r,ProblemCode.CONTRACT_INCOMPATIBLE,"1.1 recipe requires the platform-bound candidate-map and answer-snapshot contract")
        steps={x["step_ref"]:x for x in recipe["steps"]}; candidates={c["candidate_ref"]:(step,c) for step in recipe["steps"] for c in step["candidates"]}
        if s.current_step_ref is not None and s.current_step_ref not in steps:return self._blocked(r,ProblemCode.RESULT_STALE,"current step unknown")
        expected_inputs={CharacterBuildAction.PREVIEW:set(),CharacterBuildAction.APPLY_PRESET:{"preset_ref"},CharacterBuildAction.CHOOSE:{"step_ref","candidate_ref"},CharacterBuildAction.ALLOCATE:{"step_ref","candidate_ref","budget_ref","amount"},CharacterBuildAction.REQUEST_RANDOM:{"step_ref"},CharacterBuildAction.APPLY_RANDOM_RECEIPT:{"receipt"},CharacterBuildAction.BACK:set(),CharacterBuildAction.RESET:set(),CharacterBuildAction.PAUSE:set(),CharacterBuildAction.RESUME:set(),CharacterBuildAction.CONFIRM:set()}
        if set(r.input)!=expected_inputs[r.action]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action input shape invalid")
        if s.paused and r.action not in {CharacterBuildAction.RESUME,CharacterBuildAction.RESET,CharacterBuildAction.PREVIEW}:return self._blocked(r,ProblemCode.INPUT_INVALID,"paused draft only supports preview/resume/reset")
        errors=[]
        for ref in s.selected_refs:
            if ref not in candidates:errors.append("unknown_selection")
        for ref in s.selected_refs:
            if ref in candidates:
                c=candidates[ref][1]
                if any(req not in s.selected_refs for req in c["requires"]):errors.append("eligibility")
                if any(exc in s.selected_refs for exc in c["excludes"]):errors.append("exclusion")
        for ref in s.allocations:
            if ref not in candidates or candidates[ref][0]["method"]!="point_buy":errors.append("allocation_unknown_or_wrong_step")
            elif ref not in s.selected_refs:errors.append("allocation_not_selected")
        for budget in recipe["point_budgets"]:
            spent=sum(v*candidates[k][1]["cost"] for k,v in s.allocations.items() if k in candidates and candidates[k][0]["budget_ref"]==budget["budget_ref"])
            if spent>budget["total"]:errors.append("budget_exceeded")
        for step in recipe["steps"]:
            chosen=sum(1 for ref in s.selected_refs if ref in candidates and candidates[ref][0]["step_ref"]==step["step_ref"])
            if chosen<step["minimum"] or chosen>step["maximum"]:errors.append("step_cardinality")
            if step["method"]=="platform_random" and step["step_ref"] not in s.random_receipts:errors.append("random_receipt_missing")
        public={"recipe_label":recipe["label"],"current_step":None if s.current_step_ref is None else steps.get(s.current_step_ref,{}).get("label"),"selected_count":len(s.selected_refs),"paused":s.paused,"ready_to_confirm":not errors and s.current_step_ref is None}
        if r.action is CharacterBuildAction.PREVIEW:return self._proposal(r,CharacterBuildProposalKind.PREVIEW,public,None,errors)
        if r.action is CharacterBuildAction.CONFIRM:
            if not s.final_self_confirmed or errors or s.current_step_ref is not None:return self._proposal(r,CharacterBuildProposalKind.VALIDATION,public,None,errors or ["self_confirmation_required"] ,CharacterBuildStatus.INVALID)
            return self._proposal(r,CharacterBuildProposalKind.CREATE_CANDIDATE,public,{"recipe_ref":s.recipe_ref,"draft_ref":s.draft_ref,"owner_ref":s.owner_ref,"slot_ref":s.slot_ref,"selected_refs":list(s.selected_refs),"allocations":_plain(s.allocations),"random_receipts":_plain(s.random_receipts),"authoritative_create":False},())
        if r.action is CharacterBuildAction.REQUEST_RANDOM:
            step=steps.get(str(r.input.get("step_ref")))
            if step is None or step["method"]!="platform_random" or s.current_step_ref!=step["step_ref"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"random step invalid")
            return self._proposal(r,CharacterBuildProposalKind.RANDOM_REQUEST,public,{"step_ref":step["step_ref"],"random_table_ref":step["random_table_ref"],"platform_random_required":True},())
        if r.action is CharacterBuildAction.APPLY_PRESET:
            preset=next((x for x in recipe["presets"] if x["preset_ref"]==r.input.get("preset_ref")),None)
            if preset is None:return self._blocked(r,ProblemCode.INPUT_INVALID,"preset unknown")
            return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,{"action":"apply_preset","preset_ref":preset["preset_ref"],"set_selected_refs":list(preset["values"].values()),"base_draft_revision":s.draft_revision,"platform_persist_required":True},errors)
        if r.action is CharacterBuildAction.APPLY_RANDOM_RECEIPT:
            receipt=r.input.get("receipt")
            fields={"schema","receipt_ref","recipe_sha256","draft_ref","owner_ref","slot_ref","draft_revision","step_ref","random_table_ref","candidate_refs","fingerprint"}
            if not isinstance(receipt,Mapping) or set(receipt)!=fields or receipt.get("schema")!="platform-character-build-random-receipt/1.0.0":return self._blocked(r,ProblemCode.INPUT_INVALID,"platform random receipt shape invalid")
            try:
                _ref(receipt.get("receipt_ref"),"receipt_ref");_ref(receipt.get("step_ref"),"step_ref");_ref(receipt.get("random_table_ref"),"random_table_ref");_hash(receipt.get("recipe_sha256"),"recipe_sha256");_hash(receipt.get("fingerprint"),"fingerprint")
            except CharacterBuildContractError:return self._blocked(r,ProblemCode.INPUT_INVALID,"platform random receipt refs/hashes invalid")
            material={k:_plain(v) for k,v in receipt.items() if k!="fingerprint"};step=steps.get(receipt.get("step_ref"))
            refs=receipt.get("candidate_refs")
            revision=receipt.get("draft_revision")
            if receipt.get("fingerprint")!=canonical_fingerprint(material) or receipt.get("recipe_sha256")!=s.recipe_sha256 or receipt.get("draft_ref")!=s.draft_ref or receipt.get("owner_ref")!=s.owner_ref or receipt.get("slot_ref")!=s.slot_ref or isinstance(revision,bool) or not isinstance(revision,int) or revision!=s.draft_revision or step is None or s.current_step_ref!=receipt.get("step_ref") or step["method"]!="platform_random" or step["random_table_ref"]!=receipt.get("random_table_ref") or receipt.get("receipt_ref") in s.random_receipts.values() or not isinstance(refs,(tuple,list)) or not refs or len(refs)!=len(set(refs)) or not step["minimum"]<=len(refs)<=step["maximum"] or any(ref not in {c["candidate_ref"] for c in step["candidates"]} for ref in refs):return self._blocked(r,ProblemCode.RESULT_STALE,"platform random receipt identity invalid")
            updated_receipts=dict(s.random_receipts);updated_receipts[step["step_ref"]]=receipt["receipt_ref"]
            patch={"action":"apply_random_receipt","append_selected_refs":list(refs),"set_random_receipts":updated_receipts,"base_draft_revision":s.draft_revision,"platform_persist_required":True}
            return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,patch,errors)
        if r.action is CharacterBuildAction.BACK and not recipe["allow_back"] or r.action is CharacterBuildAction.RESET and not recipe["allow_reset"] or r.action in {CharacterBuildAction.PAUSE,CharacterBuildAction.RESUME} and not recipe["allow_pause_resume"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"action disabled by recipe")
        if r.action is CharacterBuildAction.PAUSE and s.paused or r.action is CharacterBuildAction.RESUME and not s.paused:return self._blocked(r,ProblemCode.INPUT_INVALID,"pause/resume state invalid")
        if r.action is CharacterBuildAction.CHOOSE:
            ref=str(r.input.get("candidate_ref") or "");step=steps.get(r.input.get("step_ref"))
            if ref not in candidates or step is None or candidates[ref][0]["step_ref"]!=step["step_ref"] or step["method"]!="choice" or s.current_step_ref!=step["step_ref"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"candidate/step unknown or mismatched")
            candidate=candidates[ref][1];new=tuple(dict.fromkeys((*s.selected_refs,ref)))
            count=sum(1 for item in new if item in candidates and candidates[item][0]["step_ref"]==step["step_ref"])
            if count>step["maximum"] or any(req not in new for req in candidate["requires"]) or any(exc in new for exc in candidate["excludes"]):return self._blocked(r,ProblemCode.INPUT_INVALID,"candidate eligibility/cardinality invalid")
            return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,{"action":"choose","set_selected_refs":list(new),"base_draft_revision":s.draft_revision,"platform_persist_required":True},errors)
        if r.action is CharacterBuildAction.ALLOCATE:
            amount=r.input.get("amount");ref=r.input.get("candidate_ref");step=steps.get(r.input.get("step_ref"))
            if isinstance(amount,bool) or not isinstance(amount,int) or amount<0 or ref not in candidates or step is None or step["method"]!="point_buy" or candidates[ref][0]["step_ref"]!=step["step_ref"] or step["budget_ref"]!=r.input.get("budget_ref") or s.current_step_ref!=step["step_ref"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"allocation invalid")
            updated=dict(s.allocations);updated[ref]=amount;budget=next(x for x in recipe["point_budgets"] if x["budget_ref"]==step["budget_ref"]);spent=sum(value*candidates[key][1]["cost"] for key,value in updated.items() if key in candidates and candidates[key][0]["budget_ref"]==budget["budget_ref"])
            if spent>budget["total"]:return self._blocked(r,ProblemCode.INPUT_INVALID,"allocation exceeds budget")
            return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,{"action":"allocate","set_allocations":updated,"base_draft_revision":s.draft_revision,"platform_persist_required":True},errors)
        if r.action is CharacterBuildAction.BACK:
            order=[x["step_ref"] for x in recipe["steps"]];index=order.index(s.current_step_ref) if s.current_step_ref in order else len(order);target=None if index==0 else order[index-1]
            return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,{"action":"back","set_current_step_ref":target,"base_draft_revision":s.draft_revision,"platform_persist_required":True},errors)
        if r.action is CharacterBuildAction.RESET:return self._proposal(r,CharacterBuildProposalKind.DRAFT_PATCH,public,{"action":"reset","set_current_step_ref":recipe["steps"][0]["step_ref"],"set_selected_refs":[],"set_allocations":{},"set_random_receipts":{},"set_final_self_confirmed":False,"base_draft_revision":s.draft_revision,"platform_persist_required":True},())
        if r.action in {CharacterBuildAction.PAUSE,CharacterBuildAction.RESUME}:
            patch={"action":r.action.value,"set_paused":r.action is CharacterBuildAction.PAUSE,"base_draft_revision":s.draft_revision,"platform_persist_required":True}
            return self._proposal(r,CharacterBuildProposalKind.PAUSE if r.action is CharacterBuildAction.PAUSE else CharacterBuildProposalKind.DRAFT_PATCH,public,patch,errors)
        patch={"action":r.action.value,"input":_plain(r.input),"base_draft_revision":s.draft_revision,"platform_persist_required":True}
        return self._proposal(r,CharacterBuildProposalKind.PAUSE if r.action is CharacterBuildAction.PAUSE else CharacterBuildProposalKind.DRAFT_PATCH,public,patch,errors)
    def _proposal(self,r,kind,public,patch,errors,status=CharacterBuildStatus.PROPOSED):
        p=CharacterBuildProposal(CHARACTER_BUILD_PROPOSAL_SCHEMA,"build."+canonical_fingerprint({"op":r.envelope.operation_ref,"kind":kind.value})[7:39],r.envelope.operation_ref,r.snapshot.draft_revision,kind,public,patch,tuple(errors))
        x=CharacterBuildResult(CHARACTER_BUILD_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.draft_revision,status,p);return replace(x,result_fingerprint=character_build_result_fingerprint(x))
    def _blocked(self,r,code,reason):
        p=Problem(code,"evaluate character build",reason,"no draft or actor state was committed","refresh authoritative draft and retry")
        x=CharacterBuildResult(CHARACTER_BUILD_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.draft_revision,CharacterBuildStatus.BLOCKED,problems=(p,));return replace(x,result_fingerprint=character_build_result_fingerprint(x))

class CharacterBuildService:
    def __init__(self,evaluator,clock=None):self.evaluator=evaluator;self.clock=clock or(lambda:datetime.now(UTC))
    async def evaluate_character_build(self,r,bridge:PlatformBridge):
        c=CancellationCheck(r.envelope.operation_ref,r.envelope.request_fingerprint);d=datetime.fromisoformat(r.envelope.deadline_at.replace("Z","+00:00"))
        if (await bridge.is_cancelled(c)).cancelled:return self._terminal(r,CharacterBuildStatus.CANCELLED,ProblemCode.CANCELLED)
        if self.clock()>=d:return self._terminal(r,CharacterBuildStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
        x=self.evaluator.evaluate(r)
        if (await bridge.is_cancelled(c)).cancelled:return self._terminal(r,CharacterBuildStatus.CANCELLED,ProblemCode.CANCELLED)
        if self.clock()>=d:return self._terminal(r,CharacterBuildStatus.TIMED_OUT,ProblemCode.DEADLINE_EXCEEDED)
        return x
    def _terminal(self,r,status,code):
        p=Problem(code,"evaluate character build","operation cancelled or timed out","no proposal returned","resume from persisted platform draft")
        x=CharacterBuildResult(CHARACTER_BUILD_RESULT_SCHEMA,r.envelope.operation_ref,r.envelope.request_fingerprint,r.envelope.expected_revision,r.snapshot.draft_revision,status,problems=(p,));return replace(x,result_fingerprint=character_build_result_fingerprint(x))
class CharacterBuildStoryEnginePort(Protocol):
    async def evaluate_character_build(self,request:CharacterBuildRequest,bridge:PlatformBridge)->CharacterBuildResult:...
