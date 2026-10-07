"""Compile explicit known-world identities without deriving facts from artwork."""
from collections.abc import Mapping
import re

CATEGORIES = {'person': 'person', 'place': 'place', 'region': 'place', 'city': 'place',
              'emblem': 'status', 'item': 'item', 'quest': 'quest', 'ability': 'ability', 'status': 'status'}
COLORS = {'gold', 'frost', 'sun', 'earth', 'water', 'wood', 'shadow', 'arcane', 'ember', 'neutral'}


def validate_presentation(value, *, kind=None):
    if (not isinstance(value, Mapping) or set(value) != {'category', 'color_family', 'icon_ref'}
            or not isinstance(value['category'], str) or value['category'] not in CATEGORIES
            or kind is not None and CATEGORIES[value['category']] != kind
            or not isinstance(value['color_family'], str) or value['color_family'] not in COLORS
            or value['icon_ref'] is not None and (not isinstance(value['icon_ref'], str)
                or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value['icon_ref']))):
        raise ValueError('authored_world.presentation_invalid')


def known_world_entities(world):
    values = world.get('known_entities', ())
    if 'known_entities' in world and world.get('schema') != 'thirteenth-seat.opening-world/1.2.0':
        raise ValueError('authored_world.entity_contract_unsupported')
    if not isinstance(values, (list, tuple)) or len(values) > 128:
        raise ValueError('authored_world.entities_invalid')
    seen = {item['ref'] for item in (*world.get('npcs', ()), *world.get('clocks', ()))}
    seen.update(world[field]['ref'] for field in ('scene', 'quest') if field in world)
    for npc in world.get('npcs', ()):
        if 'presentation' in npc:
            if world.get('schema') != 'thirteenth-seat.opening-world/1.2.0':
                raise ValueError('authored_world.entity_contract_unsupported')
            validate_presentation(npc['presentation'], kind='person')
    fields = {'ref', 'kind', 'category', 'label', 'description', 'aliases', 'visibility', 'color_family', 'icon_ref'}
    for item in values:
        if (not isinstance(item, Mapping) or set(item) != fields or not isinstance(item['ref'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,159}', item['ref']) or item['ref'] in seen
                or not isinstance(item['kind'], str) or item['kind'] not in set(CATEGORIES.values())
                or not isinstance(item['visibility'], str) or item['visibility'] not in {'public', 'party', 'dm'}):
            raise ValueError('authored_world.entity_invalid')
        validate_presentation({key: item[key] for key in ('category', 'color_family', 'icon_ref')}, kind=item['kind'])
        if any(not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > limit
               for key, limit in (('label', 240), ('description', 2000))):
            raise ValueError('authored_world.entity_text_invalid')
        aliases = item['aliases']
        if (not isinstance(aliases, (list, tuple)) or len(aliases) > 8
                or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 240 for alias in aliases)
                or len(set(aliases)) != len(aliases) or item['label'] in aliases):
            raise ValueError('authored_world.entity_alias_invalid')
        seen.add(item['ref'])
    return values
