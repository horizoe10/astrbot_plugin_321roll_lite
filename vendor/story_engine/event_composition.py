"""Exact v0.2 EventComposition Profile contracts.

This successor registry is deliberately opt-in.  It preserves every frozen P0
contract and adds only the profiles required by the v0.2 Story Pack catalogue;
callers must pass it explicitly to ``compile_story_pack``.
"""

from __future__ import annotations

from types import MappingProxyType

from .profiles import CONFLICT_V3_PROFILE_REGISTRY, ProfileContract, ProfileRegistry


_OWNER = {
    "contract_owner": "321 Story Engine v0.2 EventComposition Registry",
    "evaluation_owner": "321 Story Engine deterministic event evaluator",
    "authority_owner": "321 Roll platform",
    "execution_owner": "321 Roll TurnCommitPlan executor",
    "projection_owner": "321 Roll safe surface projectors",
    "late_result_policy": "platform rejects cancelled expired mismatched or stale proposals without partial commit",
}

_DEFAULT_BUDGETS = {
    "max_rounds": 8,
    "max_checkpoints": 5,
    "max_loop_iterations": 2,
    "max_concurrent_fronts": 1,
    "max_cascade_events": 4,
    "max_cross_module_effects": 8,
    "max_local_ms": 500,
    "max_context_tokens": 8_000,
    "max_pressure_rounds": 4,
    "recovery_window_rounds": 3,
}


def _contract(
    profile_id: str,
    *,
    required_fields: tuple[str, ...],
    required_capabilities: tuple[str, ...] = ("event.orchestrate",),
    optional_capabilities: tuple[str, ...] = (),
    scopes: tuple[str, ...] = ("scene", "site", "region", "faction", "quest", "actor_group", "campaign"),
    safety: tuple[str, ...],
) -> ProfileContract:
    return ProfileContract(
        profile_id,
        "1.0.0",
        "P0",
        **_OWNER,
        allowed_scope_kinds=frozenset(scopes),
        required_capabilities=required_capabilities,
        allowed_capabilities=tuple(dict.fromkeys((*required_capabilities, *optional_capabilities))),
        min_checkpoints=2,
        max_checkpoints=5,
        required_profile_fields=frozenset(required_fields),
        allowed_profile_fields=frozenset(required_fields),
        budget_limits=MappingProxyType(dict(_DEFAULT_BUDGETS)),
        safety_boundaries=safety,
    )


_V02_CONTRACTS = (
    _contract(
        "opportunity_event",
        required_fields=("participation_policy", "refusal_consequence"),
        optional_capabilities=("event.project", "event.causal_ledger"),
        safety=("participation is optional", "refusal never creates a mainline penalty", "rewards require platform receipts"),
    ),
    _contract(
        "journey_event",
        required_fields=("segment_plan", "safe_exit"),
        optional_capabilities=("event.consequence", "event.project", "event.pressure"),
        safety=("every segment preserves a safe stop", "ordinary failure is delay loss separation or retreat", "terminal outcomes require dedicated authority"),
    ),
    _contract(
        "revelation_event",
        required_fields=("truth_source_policy", "disclosure_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("truth is fixed before player inference", "disclosure is bounded by audience knowledge", "the model cannot invent hidden history"),
    ),
    _contract(
        "political_procedure_event",
        required_fields=("eligibility_policy", "procedural_exit"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("speaking eligibility is explicit", "evidence and dissent remain auditable", "procedure cannot erase a safe exit"),
    ),
    _contract(
        "relationship_event",
        required_fields=("consent_policy", "refusal_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("the engine never authors player emotion", "private bonds stay audience scoped", "refusal separation and boundary changes are valid outcomes"),
    ),
    _contract(
        "world_reaction_event",
        required_fields=("cause_event_ref", "scope_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.consequence", "event.project"),
        safety=("a committed cause is mandatory", "regional reaction cannot silently become global", "platform owns authoritative state"),
    ),
    _contract(
        "turning_point_event",
        required_fields=("unresolved_commitment_policy", "route_lock_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.consequence", "event.project"),
        safety=("unresolved promises survive the branch", "route locking is explicit", "terminal consequences require platform authority"),
    ),
    _contract(
        "project_event",
        required_fields=("milestones", "maintenance_owner_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.consequence", "event.project", "event.pressure"),
        safety=("one check cannot complete a civic project", "inputs and beneficiaries remain traceable", "completion without maintenance stays fragile"),
    ),
    _contract(
        "dialogue_scene_event",
        required_fields=("consent_policy", "dignified_exit"),
        optional_capabilities=("event.causal_ledger", "event.project"),
        safety=("dialogue never overrides consent", "private knowledge remains scoped", "a dignified exit is always available"),
    ),
    _contract(
        "debate_event",
        required_fields=("evidence_policy", "rhetoric_limit"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("evidence and logic outrank scripted lines", "rhetoric cannot create facts", "dissent and withdrawal remain recorded"),
    ),
    _contract(
        "investigation_case_event",
        required_fields=("hypothesis_policy", "counterevidence_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("hypotheses must be falsifiable", "counterevidence is preserved", "wrong accusation retains correction and exit paths"),
    ),
    _contract(
        "negotiation_event",
        required_fields=("signature_policy", "unsigned_effect_policy"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.project",),
        safety=("unsigned terms have no authoritative effect", "essential rescue cannot be denied by debt", "platform receipts own committed obligations"),
    ),
    _contract(
        "calendar_slice_event",
        required_fields=("time_cost", "opportunity_cost"),
        optional_capabilities=("event.causal_ledger", "event.project"),
        safety=("time and opportunity cost are explicit", "skipped activities do not secretly resolve", "calendar results are proposals until committed"),
    ),
    _contract(
        "policy_session_event",
        required_fields=("decision_stage", "implementation_stage"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.consequence", "event.project"),
        safety=("policy decision and implementation are separate commits", "affected dissent remains visible", "public essentials keep protected minimums"),
    ),
    _contract(
        "operation_event",
        required_fields=("exposure_policy", "evacuation_route"),
        optional_capabilities=("event.causal_ledger", "event.consequence", "event.project", "event.pressure"),
        safety=("exposure is staged and observable", "failure does not force a fight to the death", "an evacuation route is disclosed before commitment"),
    ),
    _contract(
        "legacy_event",
        required_fields=("actor_confirmation_policy", "inheritance_boundary"),
        required_capabilities=("event.orchestrate", "event.causal_ledger"),
        optional_capabilities=("event.consequence", "event.project"),
        safety=("permanent fate requires actor confirmation", "office assets relationships and secrets transfer separately", "history keeps losses and dissent"),
    ),
    _contract(
        "open_scene_event",
        required_fields=("risk_ceiling", "escalation_profile"),
        optional_capabilities=("event.project", "event.pressure"),
        safety=("the scene remains low risk", "crossing the ceiling routes to a dedicated profile", "withdrawal has no hidden punishment"),
    ),
    _contract(
        "challenge_event",
        required_fields=("failure_forward_policy", "terminal_boundary"),
        optional_capabilities=("event.consequence", "event.project", "event.pressure"),
        safety=("ordinary failure opens a cost or new route", "vitality zero is signal only", "death and world termination require dedicated receipts"),
    ),
)


V02_EVENT_COMPOSITION_PROFILE_REGISTRY = ProfileRegistry(
    (*CONFLICT_V3_PROFILE_REGISTRY._contracts.values(), *_V02_CONTRACTS),
    revision="se1-v02-event-composition/1",
)


_R2_CRISIS = ProfileContract(
    'crisis_event', '1.2.0', 'P0', **_OWNER,
    allowed_scope_kinds=frozenset({'scene','site','region','faction','quest','actor_group'}),
    required_capabilities=('event.orchestrate',),
    allowed_capabilities=('event.orchestrate','event.consequence','event.project','event.pressure','actor.resource_pool','actor.vitality'),
    min_checkpoints=1, max_checkpoints=8,
    required_profile_fields=frozenset({'risk_summary'}),
    allowed_profile_fields=frozenset({'risk_summary','tactical_entry','scene_checkpoint_refs','decision_checkpoint_ref','preparation_route_refs','host_handoff_checkpoint_ref','host_review_policy'}),
    budget_limits=MappingProxyType({**_DEFAULT_BUDGETS,'max_rounds':12,'max_checkpoints':8}),
    safety_boundaries=(
        'scene handoffs follow a finite declared chain before the final decision',
        'choice preparation has no mechanical effect or interaction charge',
        'human handoff and retreat preserve committed results',
        'resource and vitality effects remain platform proposals',
    ),
)

V02_EVENT_COMPOSITION_R2_PROFILE_REGISTRY = ProfileRegistry(
    (*V02_EVENT_COMPOSITION_PROFILE_REGISTRY._contracts.values(),_R2_CRISIS),
    revision='se1-v02-event-composition/2',
)


def validate_crisis_r2_graph(profile_data,graph,initial_checkpoint_ref,choice_sets,effects,extensions):
    """Verify declared preparation and scene order; old profile contracts are unchanged."""
    nodes={n['id']:n for n in graph['nodes']};edges={e['id']:e for e in graph['edges']}
    if profile_data.get('host_review_policy') not in (None,'pause_and_return_current_checkpoint'):raise ValueError('invalid host review policy')
    scenes=profile_data.get('scene_checkpoint_refs',())
    decision=profile_data.get('decision_checkpoint_ref')
    if isinstance(scenes,(str,bytes)) or not isinstance(scenes,(tuple,list)) or any(not isinstance(x,str) for x in scenes):raise ValueError('invalid scene references')
    if decision is not None and not isinstance(decision,str):raise ValueError('invalid decision reference')
    preparations=profile_data.get('preparation_route_refs',())
    if isinstance(preparations,(str,bytes)) or not isinstance(preparations,(tuple,list)) or any(not isinstance(x,str) for x in preparations) or len(preparations)!=len(set(preparations)):raise ValueError('invalid preparation references')
    scene_root=initial_checkpoint_ref
    root_edges=[edge for edge in edges.values() if edge['from']==initial_checkpoint_ref]
    if scenes and initial_checkpoint_ref!=scenes[0] and preparations and any(edge['id'] in preparations for edge in root_edges):
        targets={edge['to'] for edge in root_edges}
        if len(targets)!=1 or initial_checkpoint_ref in targets or any(edge['id'] not in preparations or edge['outcome']!='prepare_choice' for edge in root_edges):
            raise ValueError('invalid preparation root')
        scene_root=targets.pop()
    if scenes:
        if len(scenes)!=len(set(scenes)) or scene_root!=scenes[0] or decision in scenes or decision not in nodes:raise ValueError('invalid scene chain')
        for origin,target in zip(scenes,(*scenes[1:],decision)):
            outgoing=[e for e in edges.values() if e['from']==origin]
            if not outgoing or any(e['to']!=target for e in outgoing if e['outcome']=='scene_progress') or not any(e['outcome']=='scene_progress' for e in outgoing):raise ValueError('scene handoff missing or bypassed')
            if any(e['outcome'] not in {'scene_progress','retreat_or_mitigation','human_dm'} for e in outgoing):raise ValueError('scene chain has undeclared advance')
    elif decision is not None:raise ValueError('decision requires scenes')
    check_choices=extensions.get('resolution.check/1.0.0',{}).get('choice_definitions',{})
    for ref in preparations:
        edge=edges.get(ref)
        if (not edge or edge['outcome']!='prepare_choice' or edge['from']==edge['to'] or nodes[edge['from']]['kind']!='choice'
                or nodes[edge['to']]['kind']!='choice' or nodes[edge['to']].get('exit_kind') or effects
                or any(c['choice_ref'] in check_choices for s in choice_sets for c in s['choices'] if c['route_ref']==ref)):
            raise ValueError('preparation must only expose the next choice without mechanics')
    if any(e['outcome']=='prepare_choice' and e['id'] not in preparations for e in edges.values()):raise ValueError('unregistered preparation')
    handoff=profile_data.get('host_handoff_checkpoint_ref')
    if handoff is not None and (not isinstance(handoff,str) or handoff not in nodes or nodes[handoff].get('exit_kind')!='human_dm' or not any(e['to']==handoff and e['outcome']=='human_dm' for e in edges.values())):raise ValueError('host handoff requires a real terminal route')

__all__ = ['V02_EVENT_COMPOSITION_PROFILE_REGISTRY','V02_EVENT_COMPOSITION_R2_PROFILE_REGISTRY']
