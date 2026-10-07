"""Versioned, Pack-independent rules and quick characters for brief-start play.

The Engine supplies definitions. Only the platform may roll, apply costs,
control characters or commit results. Model-generated character prose never
supplies executable numbers.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


RULE_REF = "engine.default-d20"
RULE_VERSION = "1.4.0"
ATTRIBUTE_LABELS = {
    "strength": "力量", "agility": "敏捷", "endurance": "耐力",
    "perception": "感知", "reason": "思考", "will": "意志",
    "presence": "交涉", "knowledge": "知识", "craft": "手艺",
}

_RULES = {
    "schema": "se-default-rules/1.0.0",
    "rule_ref": RULE_REF,
    "version": RULE_VERSION,
    "check_policy": "attribute-d20/1.0.0",
    "dice": {"count": 1, "sides": 20, "owner": "platform"},
    "modifier": {"source": "committed_actor_attribute", "formula": "floor((attribute-6)/2)"},
    "difficulties": {"easy": 8, "standard": 12, "hard": 16, "exceptional": 20},
    "outcomes": {"success": "total >= difficulty", "failure": "total < difficulty"},
    "attributes": ATTRIBUTE_LABELS,
    "templates": {
        "generalist": {"label": "通才", "attributes": dict.fromkeys(ATTRIBUTE_LABELS, 6)},
        "explorer": {"label": "探索者", "attributes": dict(zip(ATTRIBUTE_LABELS, (6, 8, 6, 8, 6, 6, 4, 4, 6)))},
        "envoy": {"label": "交涉者", "attributes": dict(zip(ATTRIBUTE_LABELS, (4, 4, 6, 6, 6, 8, 8, 6, 6)))},
    },
    "resources": {
        "vitality": {"label": "生命力", "initial": 10, "minimum": 0, "maximum": 10},
        "supplies": {"label": "补给", "initial": 3, "minimum": 0, "maximum": 6},
    },
    "failure_costs": {"setback": {}, "harm": {"vitality": -2}},
    "recovery": {"rest": {"cost": {"supplies": -1}, "effect": {"vitality": 3}, "requires_safe_scene": True}},
    "resource_gains": {"supplies_found": {"supplies": 1}},
    "incapacitation": {"at_vitality": 0, "state": "incapacitated", "automatic_death": False,
                       "allowed_actions": ["speak", "seek_help", "rest"]},
    "risk": {"check_every_world_advances": 1, "trigger_numerator": 2, "trigger_denominator": 100,
             "minimum_gap_world_advances": 3, "maximum_per_chapter": 1, "maximum_active": 1,
             "response_window_rounds": 8, "response_kinds": ["intervention", "evacuation", "rescue"],
             "terminal_condition": "response_window_expired_without_success", "terminal_outcome": "party_destroyed"},
    "model_budget": {"intent": 1, "narrative": 1, "known_failure_repair": 1, "total_requests": 3},
    "collective_event_cadence": {
        "schema": "se-collective-event-cadence/1.0.0",
        "unit": "completed_personal_turn", "minimum": 8, "maximum": 15,
        "sampling": "uniform_inclusive_once", "release_boundary": "public_narrative_commit",
    },
    "hosting_contracts": {"intent":"se-hosted-intent-model-output/1.1.0", "narrative":"se-hosted-narrative-model-output/1.1.0"},
}


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def default_rules():
    result = deepcopy(_RULES)
    result["sha256"] = fingerprint(result)
    return result


def quick_character(template_ref, display_name, description=""):
    """Return an uncommitted template; identity and ownership are platform input."""
    if not isinstance(template_ref, str) or template_ref not in _RULES["templates"]:
        raise ValueError("quick_character.template_invalid")
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80:
        raise ValueError("quick_character.name_invalid")
    if not isinstance(description, str) or len(description) > 1200:
        raise ValueError("quick_character.description_invalid")
    template = _RULES["templates"][template_ref]
    return {
        "schema": "se-quick-character-proposal/1.0.0", "committed": False,
        "rule_ref": RULE_REF, "rule_version": RULE_VERSION, "rule_sha256": default_rules()["sha256"],
        "template_ref": template_ref, "display_name": display_name.strip(), "description": description.strip(),
        "attributes": deepcopy(template["attributes"]),
        "resources": {key: value["initial"] for key, value in _RULES["resources"].items()},
    }


def validate_brief(value):
    if not isinstance(value, dict) or set(value) - {"worldview", "opening", "tone", "boundaries", "story_pack"}:
        raise ValueError("brief.fields_invalid")
    result = {}
    for key, limit, default in (("worldview", 6000, None), ("opening", 3000, None),
                                ("tone", 300, "冒险、人物互动与探索并重"), ("boundaries", 1000, "")):
        text = value.get(key, default)
        if not isinstance(text, str) or len(text) > limit or default is None and not text.strip():
            raise ValueError("brief." + key + "_invalid")
        result[key] = text.strip()
    if value.get('story_pack') is not None:
        pack=value['story_pack']
        fields={'schema','ref','version','title','capabilities','rules','hard_facts','sha256'}
        if not isinstance(pack,dict) or set(pack)!=fields:
            raise ValueError('brief.pack_invalid')
        if (pack['schema']!='se-hosting-story-pack/1.0.0'
                or pack['capabilities']!=['author.public_hard_facts/1.0.0','rules.default_d20/1.0.0']
                or pack['rules']!={'ref':RULE_REF,'version':RULE_VERSION,'overrides':{}}
                or pack['sha256']!=fingerprint({k:v for k,v in pack.items() if k!='sha256'})
                or not isinstance(pack['hard_facts'],list) or not 1<=len(pack['hard_facts'])<=24
                or any(not isinstance(f,str) or not f.strip() or len(f)>500 for f in pack['hard_facts'])):
            raise ValueError('brief.pack_incompatible')
        result['story_pack']=deepcopy(pack)
    return result


def default_source():
    """No synthetic Story Pack identity is used for the Engine defaults."""
    return {"kind": "room_brief", "story_pack": None,
            "rules": {"ref": RULE_REF, "version": RULE_VERSION, "sha256": default_rules()["sha256"]}}
