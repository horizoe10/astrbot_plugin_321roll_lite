"""Deterministic, proposal-only runtime for compiled character-build 1.1 recipes.

This module deliberately knows nothing about accounts, databases, actors, CAS,
randomness, channels, or model providers.  It maps a frozen platform answer
snapshot plus one action to either a platform-persistable draft patch or a
create candidate.  The platform remains authoritative for every write.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from copy import deepcopy
from enum import StrEnum
from typing import Any

from .contracts.port import canonical_fingerprint


CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA = "se-character-build-answer-snapshot/1.1.0"
CHARACTER_BUILD_V11_REQUEST_SCHEMA = "se-character-build-evaluation/1.1.0"
CHARACTER_BUILD_V11_PROPOSAL_SCHEMA = "se-character-build-proposal/1.1.0"
CHARACTER_BUILD_V11_RESULT_SCHEMA = "se-character-build-result/1.1.0"
CHARACTER_BUILD_V11_PATCH_SCHEMA = "platform-character-build-draft-patch/1.1.0"
CHARACTER_BUILD_V11_CREATE_CANDIDATE_SCHEMA = "platform-character-create-candidate/1.1.0"

# Short aliases make the versioned identities easy to consume without hiding
# which generation this module implements.
CHARACTER_BUILD_SNAPSHOT_SCHEMA = CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA
CHARACTER_BUILD_REQUEST_SCHEMA = CHARACTER_BUILD_V11_REQUEST_SCHEMA
CHARACTER_BUILD_PROPOSAL_SCHEMA = CHARACTER_BUILD_V11_PROPOSAL_SCHEMA
CHARACTER_BUILD_RESULT_SCHEMA = CHARACTER_BUILD_V11_RESULT_SCHEMA
CHARACTER_BUILD_ANSWER_SNAPSHOT_SCHEMA_V11 = CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA
CHARACTER_BUILD_EVALUATION_REQUEST_SCHEMA_V11 = CHARACTER_BUILD_V11_REQUEST_SCHEMA
CHARACTER_BUILD_PROPOSAL_SCHEMA_V11 = CHARACTER_BUILD_V11_PROPOSAL_SCHEMA
CHARACTER_BUILD_RESULT_SCHEMA_V11 = CHARACTER_BUILD_V11_RESULT_SCHEMA

_RECIPE_SCHEMA = "se-character-build-recipe-ir/1.1.0"
_CATALOG_SCHEMA = "se-character-build-catalog-ir/1.1.0"
_RECIPE_SCHEMAS = {_RECIPE_SCHEMA, 'se-character-build-recipe-ir/1.2.0'}
_CATALOG_SCHEMAS = {_CATALOG_SCHEMA, 'se-character-build-catalog-ir/1.2.0'}
_ACTIONS = frozenset(
    {"preview", "submit_text", "choose", "skip", "back", "reset", "pause", "resume", "confirm_candidate"}
)
_ACTION_FIELDS = {
    "preview": frozenset(),
    "submit_text": frozenset({"step_ref", "text"}),
    "choose": frozenset({"step_ref", "selection_ref"}),
    "skip": frozenset({"step_ref"}),
    "back": frozenset(),
    "reset": frozenset(),
    "pause": frozenset(),
    "resume": frozenset(),
    "confirm_candidate": frozenset({"confirmed_draft_revision", "confirmed_snapshot_fingerprint"}),
}
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema",
        "draft_ref",
        "draft_revision",
        "recipe_ref",
        "recipe_sha256",
        "current_step_ref",
        "answers",
        "paused",
        "ready_to_confirm",
        "fingerprint",
    }
)
_REQUEST_FIELDS = frozenset(
    {"schema", "operation_ref", "request_fingerprint", "expected_draft_revision", "action", "snapshot", "input"}
)
_PROPOSAL_FIELDS = frozenset(
    {
        "schema",
        "proposal_ref",
        "operation_ref",
        "source_draft_ref",
        "source_draft_revision",
        "source_snapshot_fingerprint",
        "kind",
        "public_view",
        "platform_patch",
        "create_candidate",
        "requires_platform_commit",
        "creates_actor",
    }
)
_RESULT_FIELDS = frozenset(
    {"schema", "operation_ref", "request_fingerprint", "status", "proposal", "problems", "result_fingerprint"}
)
_PATCH_FIELDS = frozenset(
    {
        "schema",
        "base_draft_ref",
        "base_draft_revision",
        "base_snapshot_fingerprint",
        "action",
        "set_current_step_ref",
        "set_answers",
        "remove_answer_refs",
        "set_paused",
        "set_ready_to_confirm",
        "platform_persist_required",
    }
)
_CREATE_FIELDS = frozenset(
    {
        "schema",
        "draft_ref",
        "draft_revision",
        "snapshot_fingerprint",
        "recipe_ref",
        "recipe_sha256",
        "answers",
        "authoritative_create",
    }
)
_ZERO_HASH = "sha256:" + "0" * 64


class CharacterBuildV11Action(StrEnum):
    PREVIEW = "preview"
    SUBMIT_TEXT = "submit_text"
    CHOOSE = "choose"
    SKIP = "skip"
    BACK = "back"
    RESET = "reset"
    PAUSE = "pause"
    RESUME = "resume"
    CONFIRM_CANDIDATE = "confirm_candidate"


class CharacterBuildV11ContractError(ValueError):
    """Stable fail-closed contract error."""

    def __init__(self, code: str, path: str, reason: str):
        self.code = code
        self.path = path
        self.reason = reason
        super().__init__(f"{code}:{path}: {reason}")


def _fail(code: str, path: str, reason: str) -> None:
    raise CharacterBuildV11ContractError(code, path, reason)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("character_build_v11.object_invalid", path, "must be an object")
    return value


def _exact(value: Mapping[str, Any], fields: frozenset[str], path: str) -> None:
    if set(value) != fields:
        _fail("character_build_v11.fields_invalid", path, "missing or unknown fields")


def _text(value: Any, path: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("character_build_v11.text_invalid", path, "must be bounded non-empty text")
    return value


def _ref(value: Any, path: str) -> str:
    value = _text(value, path)
    if not value[0].isalnum() or any(not (char.isalnum() or char in "_.:@-") for char in value):
        _fail("character_build_v11.ref_invalid", path, "must be an opaque ref")
    return value


def _hash(value: Any, path: str) -> str:
    value = _text(value, path, 71)
    if len(value) != 71 or not value.startswith("sha256:") or any(char not in "0123456789abcdef" for char in value[7:]):
        _fail("character_build_v11.hash_invalid", path, "must be a SHA-256 identity")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("character_build_v11.integer_invalid", path, "must be a non-negative integer")
    return value


def character_build_v11_snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    value = _mapping(snapshot, "snapshot")
    return canonical_fingerprint({key: _plain(item) for key, item in value.items() if key != "fingerprint"})


def character_build_v11_request_fingerprint(request: Mapping[str, Any]) -> str:
    value = _mapping(request, "request")
    material = {key: _plain(item) for key, item in value.items() if key not in {"request_fingerprint", "snapshot"}}
    snapshot = _mapping(value.get("snapshot"), "request.snapshot")
    material["snapshot_fingerprint"] = snapshot.get("fingerprint")
    return canonical_fingerprint(material)


def character_build_v11_result_fingerprint(result: Mapping[str, Any]) -> str:
    value = _mapping(result, "result")
    return canonical_fingerprint({key: _plain(item) for key, item in value.items() if key != "result_fingerprint"})


# Compatibility aliases for callers that import the module-specific functions
# without repeating ``v11`` in every call site.
character_build_snapshot_fingerprint = character_build_v11_snapshot_fingerprint
character_build_request_fingerprint = character_build_v11_request_fingerprint
character_build_result_fingerprint = character_build_v11_result_fingerprint


def seal_character_build_v11_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy carrying its canonical fingerprint; useful at platform boundaries."""

    value = _plain(_mapping(snapshot, "snapshot"))
    value["fingerprint"] = character_build_v11_snapshot_fingerprint(value)
    return value


def seal_character_build_v11_request(request: Mapping[str, Any]) -> dict[str, Any]:
    value = _plain(_mapping(request, "request"))
    value["request_fingerprint"] = character_build_v11_request_fingerprint(value)
    return value


def _extract_recipe(compiled: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(compiled, "compiled")
    if value.get("schema") in _RECIPE_SCHEMAS:
        recipe = _plain(value)
    elif value.get("schema") in _CATALOG_SCHEMAS:
        if set(value) != {"schema", "recipes", "non_recipe_actions", "candidate_catalog_schema", "catalog_sha256"}:
            _fail("character_build_v11.catalog_invalid", "compiled", "catalog fields invalid")
        if value.get("catalog_sha256") != canonical_fingerprint({key: _plain(item) for key, item in value.items() if key != "catalog_sha256"}):
            _fail("character_build_v11.catalog_identity_invalid", "compiled.catalog_sha256", "catalog fingerprint mismatch")
        recipes = value.get("recipes")
        if not isinstance(recipes, Sequence) or isinstance(recipes, (str, bytes, bytearray)) or len(recipes) != 1:
            _fail("character_build_v11.catalog_invalid", "compiled.recipes", "exactly one 1.1 recipe is required")
        recipe = _plain(_mapping(recipes[0], "compiled.recipes[0]"))
        if recipe.get('schema')!=value['schema'].replace('catalog-ir','recipe-ir'):
            _fail('character_build_v11.recipe_invalid','compiled.recipe','catalog and recipe versions differ')
    else:
        definitions = value.get("character_build_definitions")
        if not isinstance(definitions, Mapping):
            _fail("character_build_v11.recipe_missing", "compiled", "compiled 1.1 recipe is missing")
        return _extract_recipe(definitions)
    if recipe.get("schema") not in _RECIPE_SCHEMAS:
        _fail("character_build_v11.recipe_invalid", "compiled.recipe", "recipe schema is not 1.1")
    expected = canonical_fingerprint({key: item for key, item in recipe.items() if key != "recipe_sha256"})
    if recipe.get("recipe_sha256") != expected:
        _fail("character_build_v11.recipe_identity_invalid", "compiled.recipe.recipe_sha256", "recipe fingerprint mismatch")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or len(steps) != 30:
        _fail("character_build_v11.recipe_invalid", "compiled.recipe.steps", "exactly 30 nodes are required")
    if [step.get("ordinal") for step in steps] != list(range(1, 31)):
        _fail("character_build_v11.recipe_invalid", "compiled.recipe.steps", "node ordinals must be contiguous")
    if steps[0].get("method") != "player_text" or steps[14].get("method") != "computed_checkpoint":
        _fail("character_build_v11.recipe_invalid", "compiled.recipe.steps", "frozen 1.1 node methods are invalid")
    refs = [step.get("step_ref") for step in steps]
    if len(set(refs)) != 30:
        _fail("character_build_v11.recipe_invalid", "compiled.recipe.steps", "node refs must be unique")
    for index, step in enumerate(steps):
        if any(dependency not in refs[:index] for dependency in step.get("depends_on", ())):
            _fail("character_build_v11.recipe_invalid", f"compiled.recipe.steps[{index}].depends_on", "dependency must precede node")
        if step.get("method") == "choice":
            candidates = step.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                _fail("character_build_v11.recipe_invalid", f"compiled.recipe.steps[{index}].candidates", "resolved candidates required")
            selection_refs = [candidate.get("selection_ref") for candidate in candidates]
            if len(selection_refs) != len(set(selection_refs)):
                _fail("character_build_v11.recipe_invalid", f"compiled.recipe.steps[{index}].candidates", "selection refs duplicate")
    if recipe['schema']=='se-character-build-recipe-ir/1.2.0':
        from .character_build_selection import validate_selection_rules, SelectionRuleError
        try:validate_selection_rules(recipe['selection_rules'],[step for step in steps if step['method']=='choice'])
        except (SelectionRuleError,KeyError,TypeError):_fail('character_build_v11.selection_rules_invalid','compiled.recipe.selection_rules','selection rules failed identity/dependency validation')
    elif 'selection_rules' in recipe:
        _fail('character_build_v11.selection_rules_invalid','compiled.recipe.selection_rules','1.1 recipes cannot enable 1.2 selection semantics')
    return recipe


class CharacterBuildV11Evaluator:
    """Pure evaluator for one compiled, resolved 1.1 recipe."""

    def __init__(self, compiled: Mapping[str, Any]):
        self.recipe = _extract_recipe(compiled)
        self.steps = tuple(self.recipe["steps"])
        self.step_by_ref = {step["step_ref"]: step for step in self.steps}
        self.index_by_ref = {step["step_ref"]: index for index, step in enumerate(self.steps)}
        self.candidate_by_selection = {
            candidate["selection_ref"]: (step, candidate)
            for step in self.steps
            if step["method"] == "choice"
            for candidate in step["candidates"]
        }
        descendants: dict[str, set[str]] = {step["step_ref"]: set() for step in self.steps}
        for step in self.steps:
            for dependency in step["depends_on"]:
                descendants[dependency].add(step["step_ref"])
        changed = True
        while changed:
            changed = False
            for ref in descendants:
                closure = set(descendants[ref])
                for child in tuple(closure):
                    closure.update(descendants[child])
                if closure != descendants[ref]:
                    descendants[ref] = closure
                    changed = True
        self.descendants = {ref: frozenset(items) for ref, items in descendants.items()}

    def decode_snapshot(self, value: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = _plain(_mapping(value, "snapshot"))
        _exact(snapshot, _SNAPSHOT_FIELDS, "snapshot")
        if snapshot.get("schema") != CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA:
            _fail("character_build_v11.schema_invalid", "snapshot.schema", "snapshot schema identity mismatch")
        _ref(snapshot.get("draft_ref"), "snapshot.draft_ref")
        _integer(snapshot.get("draft_revision"), "snapshot.draft_revision")
        if snapshot.get("recipe_ref") != self.recipe["recipe_ref"] or snapshot.get("recipe_sha256") != self.recipe["recipe_sha256"]:
            _fail("character_build_v11.recipe_identity_invalid", "snapshot", "snapshot recipe identity mismatch")
        current = snapshot.get("current_step_ref")
        if current is not None and current not in self.step_by_ref:
            _fail("character_build_v11.step_unknown", "snapshot.current_step_ref", "current node is not in the recipe")
        if not isinstance(snapshot.get("paused"), bool) or not isinstance(snapshot.get("ready_to_confirm"), bool):
            _fail("character_build_v11.boolean_invalid", "snapshot", "paused/ready_to_confirm must be booleans")
        _hash(snapshot.get("fingerprint"), "snapshot.fingerprint")
        if snapshot["fingerprint"] != character_build_v11_snapshot_fingerprint(snapshot):
            _fail("character_build_v11.snapshot_stale", "snapshot.fingerprint", "answer snapshot fingerprint mismatch")
        answers = _mapping(snapshot.get("answers"), "snapshot.answers")
        unknown = set(answers) - set(self.step_by_ref)
        if unknown:
            _fail("character_build_v11.answer_unknown", "snapshot.answers", "answer references an unknown node")
        accepted: dict[str, dict[str, Any]] = {}
        for step in self.steps:
            ref = step["step_ref"]
            if ref not in answers:
                continue
            if any(dependency not in accepted for dependency in step["depends_on"]):
                _fail("character_build_v11.answer_dependency_missing", f"snapshot.answers.{ref}", "answer dependency is absent")
            answer = _plain(_mapping(answers[ref], f"snapshot.answers.{ref}"))
            self._validate_answer(step, answer, accepted)
            accepted[ref] = answer
        complete = all(step["step_ref"] in accepted for step in self.steps)
        # A completed answer set can still be opened at an earlier question.
        # Confirmation becomes available again when that review is finished.
        if snapshot["ready_to_confirm"] != (complete and current is None) or (current is None and not complete):
            _fail("character_build_v11.snapshot_state_invalid", "snapshot", "ready/current state does not match answers")
        snapshot["answers"] = accepted
        return snapshot

    def decode_request(self, value: Mapping[str, Any]) -> dict[str, Any]:
        request = _plain(_mapping(value, "request"))
        _exact(request, _REQUEST_FIELDS, "request")
        if request.get("schema") != CHARACTER_BUILD_V11_REQUEST_SCHEMA:
            _fail("character_build_v11.schema_invalid", "request.schema", "request schema identity mismatch")
        _ref(request.get("operation_ref"), "request.operation_ref")
        _hash(request.get("request_fingerprint"), "request.request_fingerprint")
        _integer(request.get("expected_draft_revision"), "request.expected_draft_revision")
        action = request.get("action")
        if action not in _ACTIONS:
            _fail("character_build_v11.action_invalid", "request.action", "action is not registered")
        input_value = _plain(_mapping(request.get("input"), "request.input"))
        if set(input_value) != _ACTION_FIELDS[action]:
            _fail("character_build_v11.action_input_invalid", "request.input", "action input fields invalid")
        if action in {"submit_text", "choose", "skip"}:
            _ref(input_value.get("step_ref"), "request.input.step_ref")
        if action == "choose":
            _ref(input_value.get("selection_ref"), "request.input.selection_ref")
        if action == "submit_text" and not isinstance(input_value.get("text"), str):
            _fail("character_build_v11.action_input_invalid", "request.input.text", "text must be a string")
        if action == "confirm_candidate":
            _integer(input_value.get("confirmed_draft_revision"), "request.input.confirmed_draft_revision")
            _hash(input_value.get("confirmed_snapshot_fingerprint"), "request.input.confirmed_snapshot_fingerprint")
        request["snapshot"] = self.decode_snapshot(_mapping(request.get("snapshot"), "request.snapshot"))
        request["input"] = input_value
        return request

    def evaluate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        request = self.decode_request(value)
        snapshot = request["snapshot"]
        if request["request_fingerprint"] != character_build_v11_request_fingerprint(request):
            return self._blocked(request, "character_build_v11.request_stale", "request fingerprint mismatch")
        if request["expected_draft_revision"] != snapshot["draft_revision"]:
            return self._blocked(request, "character_build_v11.revision_stale", "expected draft revision mismatch")
        action = request["action"]
        if snapshot["paused"] and action not in {"preview", "resume", "reset"}:
            return self._blocked(request, "character_build_v11.paused", "paused draft only accepts preview, resume, or reset")
        if action == "preview":
            return self._proposed(request, "preview", self._public_view(snapshot), None, None)
        if action == "pause":
            if snapshot["paused"]:
                return self._blocked(request, "character_build_v11.pause_state_invalid", "draft is already paused")
            return self._patch_result(request, "pause", {}, (), snapshot["current_step_ref"], True)
        if action == "resume":
            if not snapshot["paused"]:
                return self._blocked(request, "character_build_v11.resume_state_invalid", "draft is not paused")
            set_answers, current = self._run_checkpoints(dict(snapshot["answers"]), snapshot["current_step_ref"])
            return self._patch_result(request, "resume", set_answers, (), current, False)
        if action == "reset":
            return self._patch_result(request, "reset", {}, tuple(snapshot["answers"]), self.steps[0]["step_ref"], False)
        if action == "back":
            target = self._back_target(snapshot)
            if target is None:
                return self._blocked(request, "character_build_v11.back_unavailable", "there is no previous interactive node")
            return self._patch_result(request, "back", {}, (), target, False)
        if action == "confirm_candidate":
            return self._confirm(request)
        step_ref = request["input"]["step_ref"]
        if step_ref != snapshot["current_step_ref"] or step_ref not in self.step_by_ref:
            return self._blocked(request, "character_build_v11.step_stale", "action node does not match current node")
        step = self.step_by_ref[step_ref]
        if action == "submit_text":
            if step["method"] != "player_text":
                return self._blocked(request, "character_build_v11.action_method_invalid", "submit_text requires player_text node")
            try:
                answer = self._text_answer(step, request["input"]["text"])
            except CharacterBuildV11ContractError as exc:
                return self._blocked(request, exc.code, exc.reason)
        elif action == "choose":
            if step["method"] != "choice":
                return self._blocked(request, "character_build_v11.action_method_invalid", "choose requires choice node")
            selection = request["input"]["selection_ref"]
            found = self.candidate_by_selection.get(selection)
            if found is None or found[0]["step_ref"] != step_ref:
                return self._blocked(request, "character_build_v11.candidate_unknown", "selection is not a candidate of current node")
            candidate = found[1]
            if not self._candidate_eligible(step, candidate, snapshot["answers"]):
                return self._blocked(request, "character_build_v11.candidate_ineligible", "candidate fails deterministic resolver metadata")
            answer = {"kind": "choice", "selection_ref": selection, "source_ref": candidate["source_ref"]}
        else:  # skip
            if step["method"] != "choice" or not step.get("optional"):
                return self._blocked(request, "character_build_v11.skip_invalid", "only optional choice nodes can be skipped")
            answer = {"kind": "skipped"}
        answers = dict(snapshot["answers"])
        changed = answers.get(step_ref) != answer
        parameter_only = changed and self._parameter_only_change(step_ref, answer, answers)
        removed = tuple(
            ref
            for ref in sorted(self.descendants[step_ref], key=self.index_by_ref.__getitem__)
            if changed and not parameter_only and ref in answers
        )
        for ref in removed:
            answers.pop(ref, None)
        answers[step_ref] = answer
        refreshed={}
        if parameter_only:
            for dependent in self.steps:
                ref=dependent['step_ref']
                if dependent['method']=='computed_checkpoint' and ref in self.descendants[step_ref] and ref in answers:
                    refreshed[ref]=self._checkpoint_answer(dependent,answers)
                    answers[ref]=refreshed[ref]
        next_ref = self._next_incomplete_after(step_ref, answers)
        checkpoint_answers, next_ref = self._run_checkpoints(answers, next_ref)
        set_answers = {step_ref: answer, **refreshed, **checkpoint_answers}
        return self._patch_result(request, action, set_answers, removed, next_ref, False)

    def _validate_answer(self, step: Mapping[str, Any], answer: dict[str, Any], accepted: Mapping[str, Any]) -> None:
        method = step["method"]
        if method == "player_text":
            if set(answer) != {"kind", "value"} or answer.get("kind") != "text":
                _fail("character_build_v11.answer_invalid", f"snapshot.answers.{step['step_ref']}", "player_text answer shape invalid")
            expected = self._text_answer(step, answer.get("value"))
            if answer != expected:
                _fail("character_build_v11.answer_invalid", f"snapshot.answers.{step['step_ref']}", "text answer is not normalized")
        elif method == "computed_checkpoint":
            fields = {"kind", "computation_ref", "dependency_fingerprint", "summary"}
            if set(answer) != fields or answer.get("kind") != "computed_checkpoint" or answer.get("computation_ref") != step["computation_ref"]:
                _fail("character_build_v11.answer_invalid", f"snapshot.answers.{step['step_ref']}", "checkpoint answer shape invalid")
            expected = self._checkpoint_answer(step, accepted)
            if answer != expected:
                _fail("character_build_v11.checkpoint_stale", f"snapshot.answers.{step['step_ref']}", "checkpoint dependency identity or summary mismatch")
        elif answer == {"kind": "skipped"}:
            if not step.get("optional"):
                _fail("character_build_v11.answer_invalid", f"snapshot.answers.{step['step_ref']}", "required choice cannot be skipped")
        else:
            if set(answer) != {"kind", "selection_ref", "source_ref"} or answer.get("kind") != "choice":
                _fail("character_build_v11.answer_invalid", f"snapshot.answers.{step['step_ref']}", "choice answer shape invalid")
            found = self.candidate_by_selection.get(answer.get("selection_ref"))
            if found is None or found[0]["step_ref"] != step["step_ref"] or found[1]["source_ref"] != answer.get("source_ref"):
                _fail("character_build_v11.answer_identity_invalid", f"snapshot.answers.{step['step_ref']}", "selection/source identity mismatch")
            if not self._candidate_eligible(step, found[1], accepted):
                _fail("character_build_v11.answer_ineligible", f"snapshot.answers.{step['step_ref']}", "stored candidate is no longer eligible")

    def _text_answer(self, step: Mapping[str, Any], value: Any) -> dict[str, Any]:
        if not isinstance(value, str):
            _fail("character_build_v11.player_text_invalid", "request.input.text", "text must be a string")
        contract = step["text_contract"]
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not contract.get("allow_empty") and not normalized:
            _fail("character_build_v11.player_text_invalid", "request.input.text", "text is required")
        if not contract["minimum_characters"] <= len(normalized) <= contract["maximum_characters"]:
            _fail("character_build_v11.player_text_invalid", "request.input.text", "text length is outside the recipe contract")
        if contract.get("reject_control_characters") and any(unicodedata.category(char).startswith("C") for char in normalized):
            _fail("character_build_v11.player_text_invalid", "request.input.text", "control characters are forbidden")
        # The Engine performs no prompt interpretation.  Reject only explicit
        # instruction-role markers; ordinary prose remains untouched.
        lowered = normalized.casefold()
        if contract.get("reject_dangerous_injection_markers") and any(
            marker in lowered for marker in ("<|system|>", "<|assistant|>", "[system]", "```system")
        ):
            _fail("character_build_v11.player_text_invalid", "request.input.text", "dangerous instruction marker is forbidden")
        return {"kind": "text", "value": normalized}

    def _selected_sources(self, answers: Mapping[str, Any], refs: Sequence[str] | None = None) -> set[str]:
        allowed = None if refs is None else set(refs)
        return {
            answer["source_ref"]
            for ref, answer in answers.items()
            if (allowed is None or ref in allowed) and answer.get("kind") == "choice"
        }

    def _parameter_only_change(self,step_ref,answer,answers):
        old=answers.get(step_ref,{})
        return bool(self.recipe.get('selection_rules') and old.get('kind')=='choice' and answer.get('kind')=='choice' and old.get('source_ref')==answer.get('source_ref') and answer['source_ref'] in self.recipe['selection_rules']['variants'])

    def _source_for(self, answers: Mapping[str, Any], step_ref: str) -> str | None:
        answer = answers.get(step_ref)
        return answer.get("source_ref") if isinstance(answer, Mapping) and answer.get("kind") == "choice" else None

    def _candidate_eligible(self, step: Mapping[str, Any], candidate: Mapping[str, Any], answers: Mapping[str, Any]) -> bool:
        # Revising this node replaces its answer and invalidates descendants.
        # Only the answers that survive that change constrain eligibility.
        replaced = self.descendants[step["step_ref"]] | {step["step_ref"]}
        answers = {ref: answer for ref, answer in answers.items() if ref not in replaced}
        metadata = candidate.get("resolver_metadata")
        if not isinstance(metadata, Mapping):
            return False
        if any(ref not in answers for ref in metadata.get("depends_on", ())):
            return False
        selected_sources = self._selected_sources(answers)
        source_ref = candidate.get("source_ref")
        # Different slots intentionally reuse selection material with different
        # selection_ref values.  Source identity, not display text or token, is
        # the duplicate-prevention boundary.
        if source_ref in selected_sources:
            return False
        # ``requires_source_refs`` may name upstream domain entities while an
        # older candidate map exposes only a legacy candidate source_ref.  The
        # 1.1 IR has no source-map edge with which to prove that equivalence, so
        # this basic evaluator must not guess it from labels.  Positive family
        # filtering below uses only explicit resolver_metadata relations.
        if any(ref in selected_sources for ref in candidate.get("excludes_source_refs", ())):
            return False
        excluded_sources = self._selected_sources(answers, step.get("excludes_selected_from", ()))
        if source_ref in excluded_sources:
            return False
        profession = self._source_for(answers, "build.step.profession")
        specialization = self._source_for(answers, "build.step.specialization")
        parent_profession = metadata.get("parent_profession_ref")
        parent_specialization = metadata.get("parent_specialization_ref")
        if parent_profession is not None and parent_profession != profession:
            return False
        if parent_specialization is not None and parent_specialization != specialization:
            return False
        predicates = set(metadata.get("filter_predicates", ()))
        if "specialization_parent_is_selected_profession" in predicates and metadata.get("parent_profession_ref") != profession:
            return False
        if "kind_is_attribute" in predicates and metadata.get("metric_kind") != "attribute":
            return False
        if "talent_belongs_to_selected_specialization" in predicates and (
            metadata.get("ability_kind") != "talent" or metadata.get("parent_specialization_ref") != specialization
        ):
            return False
        if "skill_belongs_to_selected_specialization" in predicates and (
            metadata.get("ability_kind") != "skill" or metadata.get("parent_specialization_ref") != specialization
        ):
            return False
        if "signature_is_false" in predicates and metadata.get("signature") is not False:
            return False
        from .character_build_selection import candidate_allowed
        skill_steps=('build.step.derived_skill_1','build.step.derived_skill_2')
        remaining=len(skill_steps)-skill_steps.index(step['step_ref'])-1 if step['step_ref'] in skill_steps else None
        if not candidate_allowed(self.recipe.get('selection_rules'),source_ref,selected_sources,skill_slots_remaining=remaining):
            return False
        if step['step_ref'] == 'build.step.initial_equipment':
            from .character_build_equipment import equipment_allowed
            if not equipment_allowed(self.recipe.get('selection_rules', {}), source_ref, selected_sources):
                return False
        return True

    def _eligible_candidates(self, step: Mapping[str, Any], answers: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [_plain(candidate) for candidate in step.get("candidates", ()) if self._candidate_eligible(step, candidate, answers)]

    def _checkpoint_answer(self, step: Mapping[str, Any], answers: Mapping[str, Any]) -> dict[str, Any]:
        dependency_answers = {ref: _plain(answers[ref]) for ref in step["depends_on"]}
        dependency_fingerprint = canonical_fingerprint(
            {
                "recipe_sha256": self.recipe["recipe_sha256"],
                "computation_ref": step["computation_ref"],
                "answers": dependency_answers,
            }
        )
        profession_selection = self.candidate_by_selection[answers["build.step.profession"]["selection_ref"]][1]
        specialization_selection = self.candidate_by_selection[answers["build.step.specialization"]["selection_ref"]][1]
        derived_step = self.step_by_ref["build.step.derived_skill_1"]
        eligible = self._eligible_candidates(derived_step, {**answers, step["step_ref"]: {"kind": "computed_checkpoint"}})
        profession_metadata = profession_selection["resolver_metadata"]
        specialization_source = specialization_selection["source_ref"]
        signature_sources = [
            candidate["source_ref"]
            for candidate in derived_step["candidates"]
            if candidate["resolver_metadata"].get("parent_specialization_ref") == specialization_source
            and candidate["resolver_metadata"].get("ability_kind") == "skill"
            and candidate["resolver_metadata"].get("signature") is True
        ]
        summary = {
            "profession_source_ref": profession_selection["source_ref"],
            "specialization_source_ref": specialization_source,
            "profession_core_skill": _plain(profession_metadata.get("core_skill")),
            "specialization_signature_skill_source_refs": signature_sources,
            "derived_skill_candidate_source_refs": [candidate["source_ref"] for candidate in eligible],
            "primary_ability_source_ref": self._source_for(answers, "build.step.primary_ability"),
            "secondary_ability_source_ref": self._source_for(answers, "build.step.secondary_ability"),
            "talent_source_refs": [
                self._source_for(answers, ref)
                for ref in ("build.step.talent_1", "build.step.talent_2", "build.step.talent_3")
            ],
            "model_calls": 0,
        }
        if self.recipe.get('selection_rules'):
            from .character_build_selection import selected_parameters
            summary['talent_parameters']=selected_parameters(self.recipe,answers)
        return {
            "kind": "computed_checkpoint",
            "computation_ref": step["computation_ref"],
            "dependency_fingerprint": dependency_fingerprint,
            "summary": summary,
        }

    def _next_incomplete_after(self, step_ref: str, answers: Mapping[str, Any]) -> str | None:
        for step in self.steps[self.index_by_ref[step_ref] + 1 :]:
            if step["step_ref"] not in answers:
                return step["step_ref"]
        return None

    def _run_checkpoints(self, answers: dict[str, Any], current: str | None) -> tuple[dict[str, Any], str | None]:
        generated: dict[str, Any] = {}
        while current is not None:
            step = self.step_by_ref[current]
            if step["method"] != "computed_checkpoint":
                break
            if any(ref not in answers for ref in step["depends_on"]):
                break
            answer = self._checkpoint_answer(step, answers)
            answers[current] = answer
            generated[current] = answer
            current = self._next_incomplete_after(current, answers)
        return generated, current

    def _back_target(self, snapshot: Mapping[str, Any]) -> str | None:
        current = snapshot["current_step_ref"]
        start = len(self.steps) if current is None else self.index_by_ref[current]
        for step in reversed(self.steps[:start]):
            if step["method"] != "computed_checkpoint":
                return step["step_ref"]
        return None

    def _public_view(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        current = snapshot["current_step_ref"]
        step = None if current is None else self.step_by_ref[current]
        candidates = [] if step is None or step["method"] != "choice" else self._eligible_candidates(step, snapshot["answers"])
        if self.recipe.get('selection_rules') and current in snapshot['answers']:
            for candidate in candidates:
                answer={'kind':'choice','selection_ref':candidate['selection_ref'],'source_ref':candidate['source_ref']}
                if answer!=snapshot['answers'][current] and not self._parameter_only_change(current,answer,snapshot['answers']):
                    candidate['replacement_labels']=[dependent['label'] for dependent in self.steps if dependent['step_ref'] in self.descendants[current] and dependent['step_ref'] in snapshot['answers'] and dependent['method']!='computed_checkpoint']
        return {
            "recipe_ref": self.recipe["recipe_ref"],
            "recipe_sha256": self.recipe["recipe_sha256"],
            "draft_ref": snapshot["draft_ref"],
            "draft_revision": snapshot["draft_revision"],
            "current_step_ref": current,
            "current_step": None if step is None else _plain(step),
            "eligible_candidates": candidates,
            "answered_node_count": len(snapshot["answers"]),
            "player_answer_count": sum(
                ref in snapshot["answers"] and step["method"] != "computed_checkpoint" for ref, step in self.step_by_ref.items()
            ),
            "paused": snapshot["paused"],
            "ready_to_confirm": snapshot["ready_to_confirm"],
        }

    def _patch_result(
        self,
        request: Mapping[str, Any],
        action: str,
        set_answers: Mapping[str, Any],
        remove_answer_refs: Sequence[str],
        current: str | None,
        paused: bool,
    ) -> dict[str, Any]:
        snapshot = request["snapshot"]
        remaining = dict(snapshot["answers"])
        for ref in remove_answer_refs:
            remaining.pop(ref, None)
        remaining.update(set_answers)
        ready = len(remaining) == len(self.steps) and current is None
        patch = {
            "schema": CHARACTER_BUILD_V11_PATCH_SCHEMA,
            "base_draft_ref": snapshot["draft_ref"],
            "base_draft_revision": snapshot["draft_revision"],
            "base_snapshot_fingerprint": snapshot["fingerprint"],
            "action": action,
            "set_current_step_ref": current,
            "set_answers": _plain(set_answers),
            "remove_answer_refs": list(remove_answer_refs),
            "set_paused": paused,
            "set_ready_to_confirm": ready,
            "platform_persist_required": True,
        }
        _exact(patch, _PATCH_FIELDS, "proposal.platform_patch")
        projected = {**snapshot, "answers": remaining, "current_step_ref": current, "paused": paused, "ready_to_confirm": ready}
        projected["fingerprint"] = character_build_v11_snapshot_fingerprint(projected)
        return self._proposed(request, "platform_patch", self._public_view(projected), patch, None)

    def _confirm(self, request: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = request["snapshot"]
        confirmation_revision = request["input"]["confirmed_draft_revision"]
        confirmation_fingerprint = request["input"]["confirmed_snapshot_fingerprint"]
        if isinstance(confirmation_revision, bool) or confirmation_revision != snapshot["draft_revision"]:
            return self._blocked(request, "character_build_v11.confirmation_stale", "confirmed draft revision mismatch")
        if confirmation_fingerprint != snapshot["fingerprint"]:
            return self._blocked(request, "character_build_v11.confirmation_stale", "confirmed snapshot fingerprint mismatch")
        if snapshot["paused"] or not snapshot["ready_to_confirm"] or snapshot["current_step_ref"] is not None:
            return self._blocked(request, "character_build_v11.not_ready", "draft is not ready to confirm")
        candidate = {
            "schema": CHARACTER_BUILD_V11_CREATE_CANDIDATE_SCHEMA,
            "draft_ref": snapshot["draft_ref"],
            "draft_revision": snapshot["draft_revision"],
            "snapshot_fingerprint": snapshot["fingerprint"],
            "recipe_ref": snapshot["recipe_ref"],
            "recipe_sha256": snapshot["recipe_sha256"],
            "answers": deepcopy(snapshot["answers"]),
            "authoritative_create": False,
        }
        _exact(candidate, _CREATE_FIELDS, "proposal.create_candidate")
        return self._proposed(request, "create_candidate", self._public_view(snapshot), None, candidate)

    def _proposed(
        self,
        request: Mapping[str, Any],
        kind: str,
        public_view: Mapping[str, Any],
        patch: Mapping[str, Any] | None,
        create_candidate: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        proposal_ref = "build.v11." + canonical_fingerprint(
            {
                "operation_ref": request["operation_ref"],
                "request_fingerprint": request["request_fingerprint"],
                "kind": kind,
            }
        )[7:39]
        proposal = {
            "schema": CHARACTER_BUILD_V11_PROPOSAL_SCHEMA,
            "proposal_ref": proposal_ref,
            "operation_ref": request["operation_ref"],
            "source_draft_ref": request["snapshot"]["draft_ref"],
            "source_draft_revision": request["snapshot"]["draft_revision"],
            "source_snapshot_fingerprint": request["snapshot"]["fingerprint"],
            "kind": kind,
            "public_view": _plain(public_view),
            "platform_patch": None if patch is None else _plain(patch),
            "create_candidate": None if create_candidate is None else _plain(create_candidate),
            "requires_platform_commit": patch is not None or create_candidate is not None,
            "creates_actor": False,
        }
        _exact(proposal, _PROPOSAL_FIELDS, "proposal")
        result = {
            "schema": CHARACTER_BUILD_V11_RESULT_SCHEMA,
            "operation_ref": request["operation_ref"],
            "request_fingerprint": request["request_fingerprint"],
            "status": "proposed",
            "proposal": proposal,
            "problems": [],
            "result_fingerprint": _ZERO_HASH,
        }
        result["result_fingerprint"] = character_build_v11_result_fingerprint(result)
        return result

    def _blocked(self, request: Mapping[str, Any], code: str, reason: str) -> dict[str, Any]:
        result = {
            "schema": CHARACTER_BUILD_V11_RESULT_SCHEMA,
            "operation_ref": request["operation_ref"],
            "request_fingerprint": request["request_fingerprint"],
            "status": "blocked",
            "proposal": None,
            "problems": [
                {
                    "code": code,
                    "path": "request",
                    "reason": reason,
                    "committed": False,
                    "next_action": "refresh the authoritative draft and retry",
                }
            ],
            "result_fingerprint": _ZERO_HASH,
        }
        result["result_fingerprint"] = character_build_v11_result_fingerprint(result)
        return result


def decode_character_build_v11_snapshot(value: Mapping[str, Any], compiled: Mapping[str, Any]) -> dict[str, Any]:
    return CharacterBuildV11Evaluator(compiled).decode_snapshot(value)


def decode_character_build_v11_request(value: Mapping[str, Any], compiled: Mapping[str, Any]) -> dict[str, Any]:
    return CharacterBuildV11Evaluator(compiled).decode_request(value)


def decode_character_build_v11_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    proposal = _plain(_mapping(value, "proposal"))
    _exact(proposal, _PROPOSAL_FIELDS, "proposal")
    if proposal.get("schema") != CHARACTER_BUILD_V11_PROPOSAL_SCHEMA or proposal.get("creates_actor") is not False:
        _fail("character_build_v11.proposal_invalid", "proposal", "proposal identity or authority invalid")
    kind = proposal.get("kind")
    patch = proposal.get("platform_patch")
    candidate = proposal.get("create_candidate")
    if kind == "preview":
        if patch is not None or candidate is not None or proposal.get("requires_platform_commit") is not False:
            _fail("character_build_v11.proposal_invalid", "proposal", "preview cross-fields invalid")
    elif kind == "platform_patch":
        if not isinstance(patch, Mapping) or candidate is not None or proposal.get("requires_platform_commit") is not True:
            _fail("character_build_v11.proposal_invalid", "proposal", "patch cross-fields invalid")
        _exact(patch, _PATCH_FIELDS, "proposal.platform_patch")
    elif kind == "create_candidate":
        if patch is not None or not isinstance(candidate, Mapping) or proposal.get("requires_platform_commit") is not True:
            _fail("character_build_v11.proposal_invalid", "proposal", "create candidate cross-fields invalid")
        _exact(candidate, _CREATE_FIELDS, "proposal.create_candidate")
        if candidate.get("authoritative_create") is not False:
            _fail("character_build_v11.proposal_invalid", "proposal.create_candidate", "Engine cannot authoritatively create")
    else:
        _fail("character_build_v11.proposal_invalid", "proposal.kind", "proposal kind invalid")
    return proposal


def decode_character_build_v11_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _plain(_mapping(value, "result"))
    _exact(result, _RESULT_FIELDS, "result")
    if result.get("schema") != CHARACTER_BUILD_V11_RESULT_SCHEMA:
        _fail("character_build_v11.schema_invalid", "result.schema", "result schema identity mismatch")
    _hash(result.get("request_fingerprint"), "result.request_fingerprint")
    _hash(result.get("result_fingerprint"), "result.result_fingerprint")
    if result["result_fingerprint"] != character_build_v11_result_fingerprint(result):
        _fail("character_build_v11.result_stale", "result.result_fingerprint", "result fingerprint mismatch")
    if result.get("status") == "proposed":
        if result.get("problems") != [] or not isinstance(result.get("proposal"), Mapping):
            _fail("character_build_v11.result_invalid", "result", "proposed result cross-fields invalid")
        result["proposal"] = decode_character_build_v11_proposal(result["proposal"])
    elif result.get("status") == "blocked":
        if result.get("proposal") is not None or not isinstance(result.get("problems"), list) or not result["problems"]:
            _fail("character_build_v11.result_invalid", "result", "blocked result cross-fields invalid")
        problem_fields = {"code", "path", "reason", "committed", "next_action"}
        for index, problem in enumerate(result["problems"]):
            if not isinstance(problem, Mapping) or set(problem) != problem_fields or problem.get("committed") is not False:
                _fail("character_build_v11.result_invalid", f"result.problems[{index}]", "problem fields invalid")
    else:
        _fail("character_build_v11.result_invalid", "result.status", "result status invalid")
    return result


def evaluate_character_build_v11(compiled: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """One-shot pure mapping entry point."""

    return CharacterBuildV11Evaluator(compiled).evaluate(request)


# Concise aliases matching the existing character_build module's decoder style.
decode_character_build_snapshot = decode_character_build_v11_snapshot
decode_character_build_request = decode_character_build_v11_request
decode_character_build_proposal = decode_character_build_v11_proposal
decode_character_build_result = decode_character_build_v11_result
CharacterBuildV11RuntimeEvaluator = CharacterBuildV11Evaluator


__all__ = [
    "CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA",
    "CHARACTER_BUILD_V11_REQUEST_SCHEMA",
    "CHARACTER_BUILD_V11_PROPOSAL_SCHEMA",
    "CHARACTER_BUILD_V11_RESULT_SCHEMA",
    "CHARACTER_BUILD_V11_PATCH_SCHEMA",
    "CHARACTER_BUILD_V11_CREATE_CANDIDATE_SCHEMA",
    "CHARACTER_BUILD_SNAPSHOT_SCHEMA",
    "CHARACTER_BUILD_REQUEST_SCHEMA",
    "CHARACTER_BUILD_PROPOSAL_SCHEMA",
    "CHARACTER_BUILD_RESULT_SCHEMA",
    "CHARACTER_BUILD_ANSWER_SNAPSHOT_SCHEMA_V11",
    "CHARACTER_BUILD_EVALUATION_REQUEST_SCHEMA_V11",
    "CHARACTER_BUILD_PROPOSAL_SCHEMA_V11",
    "CHARACTER_BUILD_RESULT_SCHEMA_V11",
    "CharacterBuildV11Action",
    "CharacterBuildV11ContractError",
    "CharacterBuildV11Evaluator",
    "CharacterBuildV11RuntimeEvaluator",
    "character_build_v11_snapshot_fingerprint",
    "character_build_v11_request_fingerprint",
    "character_build_v11_result_fingerprint",
    "character_build_snapshot_fingerprint",
    "character_build_request_fingerprint",
    "character_build_result_fingerprint",
    "seal_character_build_v11_snapshot",
    "seal_character_build_v11_request",
    "decode_character_build_v11_snapshot",
    "decode_character_build_v11_request",
    "decode_character_build_v11_proposal",
    "decode_character_build_v11_result",
    "decode_character_build_snapshot",
    "decode_character_build_request",
    "decode_character_build_proposal",
    "decode_character_build_result",
    "evaluate_character_build_v11",
]
