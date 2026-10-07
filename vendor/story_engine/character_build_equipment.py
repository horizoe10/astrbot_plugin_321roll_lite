"""Compile and check finite starting kits against real inventory definitions."""
from collections.abc import Mapping


class BuildEquipmentError(ValueError):
    pass


def require(value, message):
    if not value:
        raise BuildEquipmentError(message)


def validate_equipment_rules(rules, by_source):
    kits, profiles = rules['equipment_kits'], rules['equipment_profiles']
    require(isinstance(kits, Mapping) and isinstance(profiles, Mapping), 'equipment maps required')
    used = set()
    for talent, refs in profiles.items():
        require(talent in by_source and all(c['resolver_metadata'].get('ability_kind') == 'talent' for c in by_source[talent]), 'equipment profile talent unknown')
        require(isinstance(refs, (list, tuple)) and 2 <= len(refs) <= 4 and all(isinstance(ref, str) and ref in kits for ref in refs), 'equipment profile needs 2-4 declared kits')
        require(len(refs) == len(set(refs)), 'duplicate equipment profile kit')
        used.update(refs)
    require(used == set(kits), 'unreachable equipment kit')
    for ref, kit in kits.items():
        require(ref in by_source and all(c['resolver_metadata'].get('equipment_bundle_ref') == ref for c in by_source[ref]), 'equipment kit has no resolved candidate')
        require(isinstance(kit, Mapping) and set(kit) == {'label', 'description', 'grants', 'required_item_refs', 'carrying_item_refs'}, 'equipment kit fields invalid')
        require(all(isinstance(kit[key], str) and 0 < len(kit[key]) <= 4000 for key in ('label', 'description')), 'equipment kit player text required')
        grants = kit['grants']
        require(isinstance(grants, (list, tuple)) and 1 <= len(grants) <= 20, 'finite kit grants required')
        require(all(isinstance(g, Mapping) and set(g) == {'item_ref', 'count'} and isinstance(g['item_ref'], str) and type(g['count']) is int and 1 <= g['count'] <= 20 for g in grants), 'kit grant identity/count invalid')
        require(len({g['item_ref'] for g in grants}) == len(grants) and sum(g['count'] for g in grants) <= 24, 'duplicate or excessive kit grant')
        required = kit['required_item_refs']
        require(isinstance(required, (list, tuple)) and all(isinstance(x, str) for x in required) and len(set(required)) == len(required), 'kit tool requirements invalid')
        require(set(required) <= {g['item_ref'] for g in grants}, 'kit missing required skill medium')
        carrying=kit['carrying_item_refs']
        require(isinstance(carrying,(list,tuple)) and all(isinstance(x,str) for x in carrying) and len(set(carrying))==len(carrying), 'kit carrying identities invalid')
        require(set(carrying)<={g['item_ref'] for g in grants}, 'kit carrying item is not granted')


def equipment_allowed(rules, source_ref, selected):
    profiles = rules.get('equipment_profiles', {})
    active = [set(refs) for talent, refs in profiles.items() if talent in selected]
    if active:
        return all(source_ref in refs for refs in active)
    return source_ref not in rules.get('equipment_kits', {})


def validate_equipment_inventory(build_catalog, inventory_catalog):
    for recipe in (build_catalog or {}).get('recipes', ()):
        kits = recipe.get('selection_rules', {}).get('equipment_kits', {})
        if not kits:
            continue
        require(inventory_catalog is not None, 'starting kits require inventory catalog')
        definitions = {d['item_ref']: d for d in inventory_catalog['definitions']}
        for kit in kits.values():
            require(set(kit['carrying_item_refs']) <= set(inventory_catalog.get('instance_attributes', {})), 'starting kit item is missing carrying unit mapping')
            for grant in kit['grants']:
                require(grant['item_ref'] in definitions, 'starting kit references missing inventory definition')
                d = definitions[grant['item_ref']]
                require(d['visibility'] in {'public', 'owner', 'party'}, 'starting kit cannot grant hidden GM inventory')
                require(d['instance_template']['quantity_min'] == 1, 'starting kit cannot initialize this item')
