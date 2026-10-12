"""The engine slice 321Roll Lite ships.

Lite calls only these modules. Its sync tool copies them, everything they import
(including imports inside functions) and the schema files they name, and nothing
else. Keep each module's imports narrow: a new import here grows every Lite install.
"""

ENTRY_MODULES = (
    "story_engine.attribute_checks",
    "story_engine.brief_start",
    "story_engine.contracts.port",
    "story_engine.custom_plays",
    "story_engine.hosted_ledger",
    "story_engine.hosted_narrative_policy",
    "story_engine.hosted_turn",
    "story_engine.versions",
    "story_engine.world_rules",
)

# Modules Lite must never pull in; a test fails when an import chain brings one back.
EXCLUDED_MODULES = (
    "story_engine.compiler",
    "story_engine.entrypoints",
    "story_engine.recovery_cycle",
    "story_engine.recovery_cycle_v2",
    "story_engine.story_flow",
)
