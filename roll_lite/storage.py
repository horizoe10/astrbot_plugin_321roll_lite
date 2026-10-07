"""SQLite persistence: one database file, one schema, short write transactions.

Every write goes through Store.tx(), which serializes writers with BEGIN
IMMEDIATE.  Model calls never run inside a transaction: callers read, release,
call the model, then commit with a revision check (rooms.revision,
actors.revision, records.revision).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .version import DATABASE_SCHEMA

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- scope: 'global' or 'group:<umo>'.  key examples: 'play.playInvestigation', 'room.seat_cap'.
CREATE TABLE IF NOT EXISTS settings(
  scope TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(scope, key));

-- One open room per group (umo).  state: lobby | running | paused | ended | closed.
-- world_json: frozen {pack, presentation} snapshot; rules_json: engine rules compiled from it.
-- scene_json: {title, description, risk?...}; clock_json: {day, slot}; data_json: owner-namespaced extras.
CREATE TABLE IF NOT EXISTS rooms(
  id TEXT PRIMARY KEY, umo TEXT NOT NULL, platform TEXT NOT NULL, group_id TEXT NOT NULL,
  state TEXT NOT NULL, world_id TEXT NOT NULL, world_json TEXT NOT NULL, rules_json TEXT NOT NULL,
  title TEXT NOT NULL, scene_json TEXT NOT NULL DEFAULT '{}', goal TEXT NOT NULL DEFAULT '',
  act INTEGER NOT NULL DEFAULT 1, chapter INTEGER NOT NULL DEFAULT 1, clock_json TEXT NOT NULL DEFAULT '{}',
  seat_cap INTEGER NOT NULL, host_user_id TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ended_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS rooms_one_open ON rooms(umo) WHERE state <> 'closed';

-- presence: present | away | left.  attributes/resources/items/skills hold the character's
-- live numbers within this room only; nothing carries to another room.
CREATE TABLE IF NOT EXISTS actors(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), user_id TEXT NOT NULL,
  user_name TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', archetype_id TEXT NOT NULL DEFAULT '',
  order_index INTEGER NOT NULL DEFAULT 0, presence TEXT NOT NULL DEFAULT 'present',
  ready INTEGER NOT NULL DEFAULT 0,
  attributes_json TEXT NOT NULL DEFAULT '{}', resources_json TEXT NOT NULL DEFAULT '{}',
  items_json TEXT NOT NULL DEFAULT '{}', skills_json TEXT NOT NULL DEFAULT '{}',
  traits_json TEXT NOT NULL DEFAULT '[]', data_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(room_id, user_id));

-- Play records shared by every engine play; seq is the room-wide '#n' players type.
CREATE TABLE IF NOT EXISTS records(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), seq INTEGER NOT NULL,
  play TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, audience TEXT NOT NULL DEFAULT 'room',
  members_json TEXT NOT NULL DEFAULT '[]', document_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(room_id, seq));
CREATE INDEX IF NOT EXISTS records_room_kind ON records(room_id, kind, state);

-- Hosted turns.  state: awaiting | resolving | done | skipped | timed_out | failed.
CREATE TABLE IF NOT EXISTS turns(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), round INTEGER NOT NULL,
  actor_id TEXT, state TEXT NOT NULL, choices_json TEXT NOT NULL DEFAULT '[]',
  deadline_at TEXT, action_text TEXT NOT NULL DEFAULT '', intent_json TEXT, receipt_json TEXT,
  narrative_json TEXT, data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS turns_room ON turns(room_id, state);

-- Room timeline.  kind examples: narration, action, check, play, vote, system, chapter.
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL REFERENCES rooms(id), kind TEXT NOT NULL,
  actor_id TEXT, text TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_room ON events(room_id, id);

-- Story memory handed to the engine (kinds: world_fact, npc_statement, player_declaration, hypothesis).
CREATE TABLE IF NOT EXISTS facts(
  room_id TEXT NOT NULL REFERENCES rooms(id), fact_ref TEXT NOT NULL, kind TEXT NOT NULL,
  subject_ref TEXT NOT NULL, text TEXT NOT NULL, source_receipt_ref TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(room_id, fact_ref));
CREATE TABLE IF NOT EXISTS npcs(
  room_id TEXT NOT NULL REFERENCES rooms(id), npc_ref TEXT NOT NULL, name TEXT NOT NULL,
  description TEXT NOT NULL, motivation TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(room_id, npc_ref));

-- Collective votes.  state: open | closed | cancelled.
CREATE TABLE IF NOT EXISTS votes(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), kind TEXT NOT NULL, title TEXT NOT NULL,
  options_json TEXT NOT NULL, ballots_json TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL,
  deadline_at TEXT, result_json TEXT, data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

-- Idempotency: one row per accepted command or background job keyed by a caller key.
CREATE TABLE IF NOT EXISTS operations(
  id TEXT PRIMARY KEY, room_id TEXT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, state TEXT NOT NULL,
  request_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS model_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, operation_ref TEXT NOT NULL, call_sequence INTEGER NOT NULL,
  contract TEXT NOT NULL, provider_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, completed_at TEXT);
CREATE INDEX IF NOT EXISTS model_calls_room ON model_calls(room_id, id);

CREATE TABLE IF NOT EXISTS saves(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), name TEXT NOT NULL,
  data_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);

-- Proactive messages that could not be delivered.  state: pending | sent | dropped.
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, umo TEXT NOT NULL, text TEXT NOT NULL, state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);

-- Custom worlds written in the WebUI and worlds installed from the market (origin_json set).
-- Built-in packs live in worlds/ and are not stored here; a market row with the same id replaces one.
CREATE TABLE IF NOT EXISTS worlds(
  id TEXT PRIMARY KEY, pack_json TEXT NOT NULL, presentation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

# Columns added after a table first shipped: (table, column, definition).  migrate() adds any that are missing.
ADDED_COLUMNS = (("model_calls", "note", "TEXT NOT NULL DEFAULT ''"),
                 ("worlds", "origin_json", "TEXT NOT NULL DEFAULT ''"))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


class RevisionConflict(RuntimeError):
    """A row changed between read and commit; the caller should re-read."""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def migrate(self) -> None:
        with self._lock:
            connection = self.connect()
            try:
                connection.executescript(SCHEMA)
                for table, column, definition in ADDED_COLUMNS:
                    if column not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                row = connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
                if row is None:
                    connection.execute("INSERT INTO meta(key,value) VALUES('schema',?)", (str(DATABASE_SCHEMA),))
                elif int(row[0]) > DATABASE_SCHEMA:
                    raise RuntimeError(f"database schema {row[0]} is newer than this plugin ({DATABASE_SCHEMA})")
            finally:
                connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One serialized write transaction; any exception rolls everything back."""
        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    # ------------------------------------------------------------ shared helpers
    @staticmethod
    def next_seq(connection: sqlite3.Connection, room_id: str) -> int:
        row = connection.execute("SELECT COALESCE(MAX(seq),0)+1 FROM records WHERE room_id=?", (room_id,)).fetchone()
        return int(row[0])

    @staticmethod
    def bump_room(connection: sqlite3.Connection, room_id: str, expected_revision: int | None = None) -> int:
        """Advance rooms.revision; with expected_revision, fail on a concurrent change."""
        if expected_revision is None:
            connection.execute("UPDATE rooms SET revision=revision+1, updated_at=? WHERE id=?", (now(), room_id))
        elif connection.execute("UPDATE rooms SET revision=revision+1, updated_at=? WHERE id=? AND revision=?",
                                (now(), room_id, expected_revision)).rowcount != 1:
            raise RevisionConflict(room_id)
        return int(connection.execute("SELECT revision FROM rooms WHERE id=?", (room_id,)).fetchone()[0])

    @staticmethod
    def add_event(connection: sqlite3.Connection, room_id: str, kind: str, text: str,
                  *, actor_id: str | None = None, data: Any = None) -> int:
        cursor = connection.execute(
            "INSERT INTO events(room_id,kind,actor_id,text,data_json,created_at) VALUES(?,?,?,?,?,?)",
            (room_id, kind, actor_id, text, dumps(data or {}), now()))
        return int(cursor.lastrowid)

    @staticmethod
    def audit(connection: sqlite3.Connection, actor: str, action: str, target: str, detail: Any = None) -> None:
        connection.execute("INSERT INTO audit(actor,action,target,detail_json,created_at) VALUES(?,?,?,?,?)",
                           (actor, action, target, dumps(detail or {}), now()))

    @staticmethod
    def get_setting(connection: sqlite3.Connection, scope: str, key: str, default: Any = None) -> Any:
        row = connection.execute("SELECT value_json FROM settings WHERE scope=? AND key=?", (scope, key)).fetchone()
        return default if row is None else loads(row[0])

    @staticmethod
    def set_setting(connection: sqlite3.Connection, scope: str, key: str, value: Any) -> None:
        connection.execute(
            "INSERT INTO settings(scope,key,value_json,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(scope,key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (scope, key, dumps(value), now()))
