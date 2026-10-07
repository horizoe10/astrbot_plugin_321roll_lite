"""ENG02-121 deterministic offline public-situation contracts.

The Engine turns one frozen author declaration into a compiled public-track
catalog (se-offline-public-catalog-ir/1.0.0 or /1.1.0) and, for one bounded
offline segment, into a reproducible proposal (se-offline-public-proposal/1.0.0
or /1.1.0).

Three properties are contractual:

* every opening, subject and source reference binds a real declared public
  source of the active Story Pack; hidden or foreign identities fail closed;
* the same snapshot always produces byte-identical output: no model call, no
  random source, no clock, no state read and no state write;
* a stage marked return_to_table is never applied automatically and is reported
  once as deferred instead.

The 1.1 family adds the public clock counter to that same shape.  A deadline
stage may advance its own public clock by one; the snapshot carries the current
value and the maximum of every deadline clock, and a stage that would push the
count past that maximum is not applied at all: it publishes no text, advances
no step and is reported once as deferred.  Reaching the maximum exactly stays a
public number and never proposes a personal ending, event terminal or resource
change.  One opening writes one clock through at most one deadline track.

The platform keeps authority over permission, CAS, idempotency, receipts and
the final commit; this module only proposes bounded public changes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts.port import canonical_fingerprint

DEFINITIONS_SCHEMA = "se-offline-public-definitions/1.0.0"
CLOCK_DEFINITIONS_SCHEMA = "se-offline-public-definitions/1.1.0"
CATALOG_SCHEMA = "se-offline-public-catalog-ir/1.0.0"
CLOCK_CATALOG_SCHEMA = "se-offline-public-catalog-ir/1.1.0"
PROPOSAL_SCHEMA = "se-offline-public-proposal/1.0.0"
CLOCK_PROPOSAL_SCHEMA = "se-offline-public-proposal/1.1.0"
SNAPSHOT_SCHEMA = "321roll-offline-public-snapshot/1.0.0"
CLOCK_SNAPSHOT_SCHEMA = "321roll-offline-public-snapshot/1.1.0"
OFFLINE_PUBLIC_CAPABILITY = "offline.public/1.0.0"

TRACK_KINDS = ("faction", "region", "deadline")
MAX_TRACKS = 32
MAX_STAGES = 12
MAX_TEXT = 240
MAX_LABEL = 240
MAX_SEGMENT_STEP = 12
MAX_POLICY_STEPS = 12
MAX_CLOCK = 1000
STEP_HOURS = (6, 12, 24)

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_DOCUMENT_FIELDS = frozenset({"schema", "tracks"})
_TRACK_FIELDS = frozenset({"track_ref", "opening_ref", "subject_ref", "kind", "label", "source_ref", "stages"})
_STAGE_FIELDS = frozenset({"step", "text", "return_to_table"})
_CLOCK_STAGE_FIELDS = frozenset({"step", "text", "return_to_table", "clock_delta"})
_CATALOG_FIELDS = frozenset({"schema", "tracks", "catalog_sha256"})
_POLICY_FIELDS = frozenset({"revision", "step_hours", "max_steps"})
_TRACK_STATE_FIELDS = frozenset({"track_ref", "step"})
_CLOCK_TRACK_STATE_FIELDS = frozenset({"track_ref", "step", "clock"})
_CLOCK_FIELDS = frozenset({"clock_ref", "current", "maximum"})
_SNAPSHOT_FIELDS = frozenset({
    "schema", "segment_ref", "checkpoint_ref", "policy", "from_step", "to_step",
    "opening_ref", "catalog", "tracks", "snapshot_sha256",
})


@dataclass(frozen=True, slots=True)
class OfflinePublicContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}:{self.reason}"


def _fail(code: str, path: str, reason: str) -> None:
    raise OfflinePublicContractError(code, path, reason)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("offline_public.object_invalid", path, "必须是一个对象。")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("offline_public.sequence_invalid", path, "必须是一个数组。")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str], path: str) -> None:
    declared = set(value)
    unknown = sorted(str(key) for key in declared - expected)
    if unknown:
        _fail("offline_public.field_unknown", path, "包含未知字段：" + "、".join(unknown))
    missing = sorted(expected - declared)
    if missing:
        _fail("offline_public.field_missing", path, "缺少字段：" + "、".join(missing))


def _text(value: object, path: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        _fail("offline_public.text_invalid", path, "必须是文本。")
    stripped = value.strip()
    if not stripped or len(stripped) > limit:
        _fail("offline_public.text_invalid", path, f"必须是 1 到 {limit} 个字符的非空文本。")
    if _CONTROL_RE.search(stripped):
        _fail("offline_public.text_invalid", path, "不得包含换行或控制字符。")
    return stripped




def _reference(value: object, path: str) -> str:
    text = _text(value, path, 160)
    if _REF_RE.fullmatch(text) is None:
        _fail("offline_public.reference_invalid", path, "必须使用活动 Pack 的稳定来源引用。")
    return text


def _identifier(value: object, path: str) -> str:
    text = _text(value, path, 128)
    if _ID_RE.fullmatch(text) is None:
        _fail("offline_public.identifier_invalid", path, "必须是小写字母开头的稳定 ID。")
    return text


def _integer(value: object, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail("offline_public.integer_invalid", path, f"必须是 {minimum} 到 {maximum} 之间的整数。")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("offline_public.boolean_invalid", path, "必须是布尔值。")
    return value


def _canonical(value: Mapping[str, Any], path: str) -> str:
    try:
        return canonical_fingerprint(value)
    except (TypeError, ValueError) as exc:
        _fail("offline_public.non_canonical_value", path, f"只接受可规范化的 JSON 数据：{exc}")


def _self_digest(value: Mapping[str, Any], field: str, code: str, path: str) -> str:
    declared = value.get(field)
    if not isinstance(declared, str) or _DIGEST_RE.fullmatch(declared) is None:
        _fail("offline_public.digest_invalid", f"{path}.{field}", "必须是 sha256: 加 64 位小写十六进制。")
    expected = _canonical({key: item for key, item in value.items() if key != field}, path)
    if declared != expected:
        _fail(code, f"{path}.{field}", "自身摘要与规范化内容不一致。")
    return declared


def opening_public_sources(openings_document: object) -> dict[str, dict[str, str]]:
    """Return opening_ref to declared public source refs with their category.

    Only identities the opening itself declares public are returned: the
    opening scene, its quest, its NPC declarations, its public clocks and its
    public world entities.  Party, DM and undeclared identities stay out, so a
    private identity can never be bound as an offline public source.
    """

    document = _mapping(openings_document, "openings_document")
    openings = document.get("openings")
    if not isinstance(openings, Sequence) or isinstance(openings, (str, bytes, bytearray)) or not openings:
        _fail("offline_public.openings_invalid", "openings_document.openings", "必须提供活动 Story Pack 的真实 openings 列表。")
    result: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(openings):
        path = f"openings_document.openings[{index}]"
        entry = _mapping(raw, path)
        opening_ref = _reference(entry.get("id"), f"{path}.id")
        if opening_ref in result:
            _fail("offline_public.openings_invalid", f"{path}.id", "开场引用重复。")
        initial_state = _mapping(entry.get("initial_state"), f"{path}.initial_state")
        world = _mapping(initial_state.get("world_initialization"), f"{path}.initial_state.world_initialization")
        sources: dict[str, str] = {}

        def declare(value: object, category: str, where: str) -> None:
            ref = _reference(value, where)
            if ref in sources:
                _fail("offline_public.openings_invalid", where, "同一开场内公开来源引用重复。")
            sources[ref] = category

        for field, category in (("scene", "scene"), ("quest", "quest")):
            declaration = world.get(field)
            if declaration is None:
                continue
            scene_path = f"{path}.world_initialization.{field}"
            declare(_mapping(declaration, scene_path).get("ref"), category, f"{scene_path}.ref")
        for npc_index, npc in enumerate(_sequence(world.get("npcs", []), f"{path}.world_initialization.npcs")):
            npc_path = f"{path}.world_initialization.npcs[{npc_index}]"
            declare(_mapping(npc, npc_path).get("ref"), "npc", f"{npc_path}.ref")
        for clock_index, clock in enumerate(_sequence(world.get("clocks", []), f"{path}.world_initialization.clocks")):
            clock_path = f"{path}.world_initialization.clocks[{clock_index}]"
            item = _mapping(clock, clock_path)
            if item.get("visibility") == "public":
                declare(item.get("ref"), "clock", f"{clock_path}.ref")
        entities = _sequence(world.get("known_entities", []), f"{path}.world_initialization.known_entities")
        for entity_index, entity in enumerate(entities):
            entity_path = f"{path}.world_initialization.known_entities[{entity_index}]"
            item = _mapping(entity, entity_path)
            if item.get("visibility") == "public":
                category = item.get("kind")
                declare(item.get("ref"), category if isinstance(category, str) and category else "entity", f"{entity_path}.ref")
        result[opening_ref] = sources
    return result


def _stages(value: object, path: str, clocked: bool) -> list[dict[str, Any]]:
    raw_stages = _sequence(value, path)
    if not 1 <= len(raw_stages) <= MAX_STAGES:
        _fail("offline_public.stage_invalid", path, f"每个轨道必须声明 1 到 {MAX_STAGES} 个公开阶段。")
    stages: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_stages):
        stage_path = f"{path}[{index}]"
        stage = _mapping(raw, stage_path)
        _fields(stage, _CLOCK_STAGE_FIELDS if clocked else _STAGE_FIELDS, stage_path)
        step = _integer(stage.get("step"), f"{stage_path}.step", 1, MAX_STAGES)
        if step != index + 1:
            _fail("offline_public.stage_invalid", f"{stage_path}.step", f"阶段 step 必须是从 1 开始的连续升序，期望 {index + 1}。")
        declared = {
            "step": step,
            "text": _text(stage.get("text"), f"{stage_path}.text"),
            "return_to_table": _boolean(stage.get("return_to_table"), f"{stage_path}.return_to_table"),
        }
        if clocked:
            declared["clock_delta"] = _integer(stage.get("clock_delta"), f"{stage_path}.clock_delta", 0, 1)
        stages.append(declared)
    return stages


def _clock_targets(tracks: Sequence[Mapping[str, Any]], path: str) -> None:
    """One opening writes one public clock through at most one deadline track.

    Two deadline tracks over the same clock would both report a change from the
    same snapshot value, so one of the two deltas would be lost at the commit
    boundary.  The duplicate write target fails closed instead.
    """

    written: set[tuple[str, str]] = set()
    for index, track in enumerate(tracks):
        if track["kind"] != "deadline":
            continue
        target = (str(track["opening_ref"]), str(track["subject_ref"]))
        if target in written:
            _fail("offline_public.clock_target_duplicate", f"{path}[{index}].subject_ref", "同一开场内最多一个 deadline 轨道可以推进同一公开时钟。")
        written.add(target)


def _track(value: object, path: str, openings: Mapping[str, Mapping[str, str]] | None, clocked: bool = False) -> dict[str, Any]:
    raw = _mapping(value, path)
    _fields(raw, _TRACK_FIELDS, path)
    track = {
        "track_ref": _identifier(raw.get("track_ref"), f"{path}.track_ref"),
        "opening_ref": _reference(raw.get("opening_ref"), f"{path}.opening_ref"),
        "subject_ref": _reference(raw.get("subject_ref"), f"{path}.subject_ref"),
        "kind": _text(raw.get("kind"), f"{path}.kind", 32),
        "label": _text(raw.get("label"), f"{path}.label", MAX_LABEL),
        "source_ref": _reference(raw.get("source_ref"), f"{path}.source_ref"),
        "stages": _stages(raw.get("stages"), f"{path}.stages", clocked),
    }
    if track["kind"] not in TRACK_KINDS:
        _fail("offline_public.kind_invalid", f"{path}.kind", "kind 只允许：" + "、".join(TRACK_KINDS) + "。")
    if clocked:
        for stage in track["stages"]:
            if stage["clock_delta"] and track["kind"] != "deadline":
                _fail("offline_public.clock_delta_invalid", f"{path}.stages[{stage['step'] - 1}].clock_delta", "只有 deadline 轨道可以推进公开计数。")
            if stage["clock_delta"] and stage["return_to_table"]:
                _fail("offline_public.clock_delta_invalid", f"{path}.stages[{stage['step'] - 1}].clock_delta", "return_to_table 阶段不得推进公开计数。")
    if openings is not None:
        sources = openings.get(track["opening_ref"])
        if sources is None:
            _fail("offline_public.opening_unknown", f"{path}.opening_ref", "该 opening_ref 不在活动 Story Pack 的真实开场中。")
        for field in ("subject_ref", "source_ref"):
            if track[field] not in sources:
                _fail("offline_public.source_unknown", f"{path}.{field}", "该引用不是此开场声明的公开来源（场景/任务/NPC/公开时钟/公开实体）。")
        allowed_subjects={"region":{"place","scene"},"faction":{"status"},"deadline":{"clock"}}
        if sources[track["subject_ref"]] not in allowed_subjects[track["kind"]]:
            _fail("offline_public.subject_kind_invalid", f"{path}.subject_ref", "公开进展主体与声明类型不符；个人身份不是离线进展主体。")
    return track


def compile_offline_public(document: object, openings_document: object) -> dict[str, Any]:
    """Compile one author declaration against the real active openings.

    Track order is the author declaration order, and a proposal reports changes
    in exactly that order.  The catalog keeps the declared author version: a
    1.0.0 declaration compiles se-offline-public-catalog-ir/1.0.0 without the
    clock counter, a 1.1.0 declaration compiles /1.1.0 with it.
    """

    raw = _mapping(document, "offline_public_document")
    _fields(raw, _DOCUMENT_FIELDS, "offline_public_document")
    declared_schema = raw.get("schema")
    if declared_schema not in (DEFINITIONS_SCHEMA, CLOCK_DEFINITIONS_SCHEMA):
        _fail("offline_public.document_invalid", "offline_public_document.schema", f"必须使用 {DEFINITIONS_SCHEMA} 或 {CLOCK_DEFINITIONS_SCHEMA}。")
    clocked = declared_schema == CLOCK_DEFINITIONS_SCHEMA
    openings = opening_public_sources(openings_document)
    raw_tracks = _sequence(raw.get("tracks"), "offline_public_document.tracks")
    if not 1 <= len(raw_tracks) <= MAX_TRACKS:
        _fail("offline_public.track_limit_invalid", "offline_public_document.tracks", f"必须声明 1 到 {MAX_TRACKS} 个公开轨道。")
    tracks = [_track(item, f"offline_public_document.tracks[{index}]", openings, clocked) for index, item in enumerate(raw_tracks)]
    seen: set[str] = set()
    for index, track in enumerate(tracks):
        if track["track_ref"] in seen:
            _fail("offline_public.track_duplicate", f"offline_public_document.tracks[{index}].track_ref", "track_ref 重复。")
        seen.add(track["track_ref"])
    if clocked:
        _clock_targets(tracks, "offline_public_document.tracks")
    missing = sorted(set(openings) - {track["opening_ref"] for track in tracks})
    if missing:
        _fail("offline_public.coverage_incomplete", "offline_public_document.tracks", "以下真实开场的公开来源尚未覆盖：" + "、".join(missing))
    catalog: dict[str, Any] = {"schema": CLOCK_CATALOG_SCHEMA if clocked else CATALOG_SCHEMA, "tracks": tracks}
    catalog["catalog_sha256"] = _canonical(catalog, "public_catalog")
    return catalog


def _catalog_tracks(catalog: object, path: str) -> tuple[bool, list[dict[str, Any]]]:
    """Return the declared catalog generation and its validated tracks."""

    raw = _mapping(catalog, path)
    _fields(raw, _CATALOG_FIELDS, path)
    declared_schema = raw.get("schema")
    if declared_schema not in (CATALOG_SCHEMA, CLOCK_CATALOG_SCHEMA):
        _fail("offline_public.catalog_invalid", f"{path}.schema", f"必须使用 {CATALOG_SCHEMA} 或 {CLOCK_CATALOG_SCHEMA}。")
    clocked = declared_schema == CLOCK_CATALOG_SCHEMA
    _self_digest(raw, "catalog_sha256", "offline_public.catalog_identity_invalid", path)
    raw_tracks = _sequence(raw.get("tracks"), f"{path}.tracks")
    if not 1 <= len(raw_tracks) <= MAX_TRACKS:
        _fail("offline_public.catalog_invalid", f"{path}.tracks", f"必须包含 1 到 {MAX_TRACKS} 个公开轨道。")
    tracks = [_track(item, f"{path}.tracks[{index}]", None, clocked) for index, item in enumerate(raw_tracks)]
    seen: set[str] = set()
    for index, track in enumerate(tracks):
        if track["track_ref"] in seen:
            _fail("offline_public.catalog_invalid", f"{path}.tracks[{index}].track_ref", "track_ref 重复。")
        seen.add(track["track_ref"])
    if clocked:
        _clock_targets(tracks, f"{path}.tracks")
    return clocked, tracks


def _policy(value: object) -> dict[str, int]:
    policy = _mapping(value, "snapshot.policy")
    _fields(policy, _POLICY_FIELDS, "snapshot.policy")
    hours=policy.get("step_hours")
    if type(hours) is not int or hours not in STEP_HOURS:
        _fail("offline_public.policy_invalid", "snapshot.policy.step_hours", "离线步长必须是 6、12 或 24 小时。")
    return {
        "revision": _integer(policy.get("revision"), "snapshot.policy.revision", 1, 1000000),
        "step_hours": hours,
        "max_steps": _integer(policy.get("max_steps"), "snapshot.policy.max_steps", 1, MAX_POLICY_STEPS),
    }


def propose_offline_public(snapshot: object) -> dict[str, Any]:
    """Return the bounded public proposal for one frozen offline segment.

    Every opening-matched track of the frozen catalog appears exactly once, in
    catalog order, including tracks already at their last stage.  A track that
    meets a return_to_table stage stops before it and reports that stage as
    deferred; no later stage is applied or reported.

    In the 1.1 family the deadline stages also accumulate their clock_delta on
    the clock the snapshot declares.  A stage whose delta would push the count
    past its maximum is reported as deferred exactly like a return_to_table
    stage: no text is published and the step does not advance.  A stage that
    lands exactly on the maximum is applied as a public number only; this
    module never proposes a personal ending, an event terminal or a resource
    change.
    """

    raw = _mapping(snapshot, "snapshot")
    _fields(raw, _SNAPSHOT_FIELDS, "snapshot")
    declared_schema = raw.get("schema")
    if declared_schema not in (SNAPSHOT_SCHEMA, CLOCK_SNAPSHOT_SCHEMA):
        _fail("offline_public.snapshot_invalid", "snapshot.schema", f"必须使用 {SNAPSHOT_SCHEMA} 或 {CLOCK_SNAPSHOT_SCHEMA}。")
    clocked = declared_schema == CLOCK_SNAPSHOT_SCHEMA
    _self_digest(raw, "snapshot_sha256", "offline_public.snapshot_identity_invalid", "snapshot")
    _reference(raw.get("segment_ref"), "snapshot.segment_ref")
    _reference(raw.get("checkpoint_ref"), "snapshot.checkpoint_ref")
    policy = _policy(raw.get("policy"))
    from_step = _integer(raw.get("from_step"), "snapshot.from_step", 0, MAX_SEGMENT_STEP)
    to_step = _integer(raw.get("to_step"), "snapshot.to_step", 0, MAX_SEGMENT_STEP)
    if from_step >= to_step:
        _fail("offline_public.range_invalid", "snapshot.from_step/snapshot.to_step", "必须满足 0 <= from_step < to_step <= 12。")
    if to_step - from_step > policy["max_steps"]:
        _fail("offline_public.budget_exceeded", "snapshot.to_step", "本次推进步数超过冻结策略的单次上限。")
    opening_ref = _reference(raw.get("opening_ref"), "snapshot.opening_ref")
    catalog = _mapping(raw.get("catalog"), "snapshot.catalog")
    catalog_clocked, tracks = _catalog_tracks(catalog, "snapshot.catalog")
    if catalog_clocked != clocked:
        _fail("offline_public.catalog_version_invalid", "snapshot.catalog.schema", f"{declared_schema} 必须搭配 {CLOCK_CATALOG_SCHEMA if clocked else CATALOG_SCHEMA} 的公开目录。")
    matched = [track for track in tracks if track["opening_ref"] == opening_ref]
    by_ref = {track["track_ref"]: track for track in matched}
    current: dict[str, int] = {}
    declared_clocks: dict[str, dict[str, Any] | None] = {}
    for index, item in enumerate(_sequence(raw.get("tracks"), "snapshot.tracks")):
        path = f"snapshot.tracks[{index}]"
        state = _mapping(item, path)
        _fields(state, _CLOCK_TRACK_STATE_FIELDS if clocked else _TRACK_STATE_FIELDS, path)
        track_ref = _identifier(state.get("track_ref"), f"{path}.track_ref")
        if track_ref in current:
            _fail("offline_public.track_duplicate", f"{path}.track_ref", "同一 track_ref 只能出现一次。")
        track = by_ref.get(track_ref)
        if track is None:
            _fail("offline_public.track_unknown", f"{path}.track_ref", "该 track_ref 不属于当前开场匹配的公开轨道。")
        current[track_ref] = _integer(state.get("step"), f"{path}.step", 0, len(track["stages"]))
        if not clocked:
            continue
        declared = state.get("clock")
        if track["kind"] != "deadline":
            if declared is not None:
                _fail("offline_public.clock_unexpected", f"{path}.clock", "只有 deadline 轨道可以携带公开时钟。")
            declared_clocks[track_ref] = None
            continue
        if declared is None:
            _fail("offline_public.clock_missing", f"{path}.clock", "deadline 轨道必须给出原公开时钟的当前值与上限。")
        clock = _mapping(declared, f"{path}.clock")
        _fields(clock, _CLOCK_FIELDS, f"{path}.clock")
        clock_ref = _reference(clock.get("clock_ref"), f"{path}.clock.clock_ref")
        if clock_ref != track["subject_ref"]:
            _fail("offline_public.clock_ref_mismatch", f"{path}.clock.clock_ref", "clock_ref 必须等于该轨道声明的 subject_ref。")
        maximum = _integer(clock.get("maximum"), f"{path}.clock.maximum", 0, MAX_CLOCK)
        declared_clocks[track_ref] = {
            "clock_ref": clock_ref,
            "current": _integer(clock.get("current"), f"{path}.clock.current", 0, maximum),
            "maximum": maximum,
        }
    missing = sorted(track["track_ref"] for track in matched if track["track_ref"] not in current)
    if missing:
        _fail("offline_public.track_missing", "snapshot.tracks", "缺少当前开场匹配的公开轨道：" + "、".join(missing))
    delta = to_step - from_step
    changes: list[dict[str, Any]] = []
    for track in matched:
        before = current[track["track_ref"]]
        target = min(before + delta, len(track["stages"]))
        texts: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        after = before
        clock = declared_clocks.get(track["track_ref"]) if clocked else None
        clock_after = clock["current"] if clock is not None else None
        for stage in track["stages"]:
            if stage["step"] <= before:
                continue
            if stage["step"] > target:
                break
            entry = {"step": stage["step"], "text": stage["text"], "source_ref": track["source_ref"]}
            if stage["return_to_table"]:
                deferred.append(entry)
                break
            if clock is not None and clock_after + stage["clock_delta"] > clock["maximum"]:
                deferred.append(entry)
                break
            if clock is not None:
                clock_after += stage["clock_delta"]
            texts.append(entry)
            after = stage["step"]
        change: dict[str, Any] = {
            "track_ref": track["track_ref"],
            "before_step": before,
            "after_step": after,
            "texts": texts,
            "deferred": deferred,
        }
        if clocked:
            change["clock"] = None if clock is None else {
                "clock_ref": clock["clock_ref"],
                "before": clock["current"],
                "after": clock_after,
                "maximum": clock["maximum"],
            }
        changes.append(change)
    proposal: dict[str, Any] = {
        "schema": CLOCK_PROPOSAL_SCHEMA if clocked else PROPOSAL_SCHEMA,
        "snapshot_sha256": raw["snapshot_sha256"],
        "catalog_sha256": catalog["catalog_sha256"],
        "from_step": from_step,
        "to_step": to_step,
        "changes": changes,
    }
    proposal["proposal_sha256"] = _canonical(proposal, "public_proposal")
    return proposal
