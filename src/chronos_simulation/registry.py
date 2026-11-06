"""Fixed registry for owned simulator scenarios, not a public API.

Only the trusted installer/controller chooses the absolute data root and calls
register/advance/close. Neither the agent nor the browser supplies file paths,
provider classes, URLs, or authoritative receipts. Native authorization and UTC
translation are separate integration concerns; this module does not grant them.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3

from .model import Blocked, canonical, fingerprint, integer, validate
from .store import Destinations, ID
from .workflow import Workflow


class Registry:
    def __init__(self, root, *, create=False):
        root=Path(root)
        if not root.is_absolute() or root.resolve()!=root:
            raise Blocked('registry_requires_fixed_absolute_root')
        self.root=root
        self.path=self._owned(root/'registry.sqlite')
        if type(create) is not bool:raise Blocked('invalid_registry_bootstrap')
        if create and not self.path.exists():
            self.root.mkdir(parents=True,exist_ok=True)
            # Bootstrap is explicit and only for an empty deployment directory.
            # A missing catalog beside surviving destinations must never reset
            # their business identity and permit a replacement acceptance.
            if any(self.root.iterdir()):raise Blocked('registry_missing_in_existing_root')
            with closing(sqlite3.connect(self.path,timeout=5)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE IF NOT EXISTS registrations (order_id TEXT PRIMARY KEY, definition TEXT NOT NULL)')
        # Ordinary reopen must not create directories, catalogs, or tables.
        with self._transaction() as db:
            db.execute('SELECT order_id,definition FROM registrations LIMIT 0')

    def _owned(self, path):
        # Reject linked/junction paths in an otherwise trusted deployment root.
        # This is not a defense against a hostile OS administrator racing I/O.
        if path.resolve()!=path or not path.is_relative_to(self.root):
            raise Blocked('registry_path_changed')
        return path

    @contextmanager
    def _transaction(self, *, write=False):
        self._owned(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _identity(order_id):
        if type(order_id) is not str or not ID.fullmatch(order_id):
            raise Blocked('invalid_order_identity')
        return order_id

    def _path(self, definition):
        # No user text is interpolated into a filesystem path.
        return self._owned(self.root/'orders'/fingerprint(definition)/'provider.sqlite')

    def register(self, world, changes=(), start=0):
        validate(world);self._identity(world['order_id']);integer(start,'start')
        changes=tuple(changes);Workflow(world,'HOLD',start,changes)
        definition={'world':world,'calendar':[asdict(c) for c in changes],'start':start}
        serialized=canonical(definition)
        # Freeze caller-owned data before any waits or filesystem writes.
        definition=json.loads(serialized)
        with self._transaction(write=True) as db:
            row=db.execute('SELECT definition FROM registrations WHERE order_id=?',(definition['world']['order_id'],)).fetchone()
            if row:
                if row[0]!=serialized:raise Blocked('registered_scenario_is_immutable')
                self._open(definition)
                return fingerprint(definition)
            path=self._path(definition)
            store=Destinations(path)
            store.initialize(definition['world'],changes,start)
            # Publish the registration only after the provider commits. A crash
            # between these commits leaves an unreferenced, retryable own store.
            db.execute('INSERT INTO registrations VALUES (?,?)',(definition['world']['order_id'],serialized))
        return fingerprint(definition)

    def _open(self, definition):
        store=Destinations(self._path(definition),existing=True)
        snapshot=store.observe()
        if snapshot['definition']!=definition['world'] or snapshot['calendar']!=definition['calendar']:
            raise Blocked('registered_destination_definition_changed')
        return store

    def _destination(self, order_id):
        self._identity(order_id)
        with self._transaction() as db:
            row=db.execute('SELECT definition FROM registrations WHERE order_id=?',(order_id,)).fetchone()
        if row is None:raise Blocked('order_not_registered')
        definition=json.loads(row[0])
        if definition['world']['order_id']!=order_id:raise Blocked('registration_identity_conflict')
        return self._open(definition)

    def observe(self, order_id):return self._destination(order_id).observe()

    def trials(self, order_id):return self._destination(order_id).trial_snapshot()

    def submit(self, attempt, *, expected_observation_id, admission_deadline):
        Destinations._binding(attempt)
        if expected_observation_id is None or admission_deadline is None:
            raise Blocked('dispatch_requires_observation_and_deadline')
        return self._destination(attempt['order_id']).submit(attempt,
            expected_observation_id=expected_observation_id,admission_deadline=admission_deadline)

    def query(self, identity):
        if type(identity) is not dict:raise Blocked('invalid_query_identity')
        return self._destination(identity.get('order_id')).query_identity(identity)

    def advance(self, order_id, until):self._destination(order_id).advance(until)

    def close(self, attempt):
        Destinations._binding(attempt)
        return self._destination(attempt['order_id']).close_unaccepted(attempt)
