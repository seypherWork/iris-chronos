"""Offline monetary authorization and durable reservations for a future cloud guard.

No key input, network, model calls, or automatic allowance creation. The existing
local guard does not enable remote execution. Rates and model context limits are
operator-reviewed inputs: this ledger is not a provider invoice or a guarantee
against provider price changes, taxes, or other applications using the same key.
"""
from contextlib import closing
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3
import time

if __package__:
    from .deployment import Profile, DeploymentError
    from .cloud_models import MODELS
else:  # Direct sibling-script use by the isolated guard launcher.
    from deployment import Profile, DeploymentError
    from cloud_models import MODELS

OUTPUT_TOKEN_LIMIT = 2048
DAY_US = 86_400_000_000
MICRO_USD_PER_USD = 1_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value):
    return sha256(canonical(value).encode('ascii')).hexdigest()


def integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


@dataclass(frozen=True)
class CloudBudgetPolicy:
    profile_sha256: str
    budget_micro_usd: int
    model_context_tokens: int
    input_micro_usd_per_million_tokens: int
    output_micro_usd_per_million_tokens: int
    created_at_us: int
    expires_at_us: int
    version: int = 1

    def __post_init__(self):
        if type(self.profile_sha256) is not str or not re.fullmatch(r'[a-f0-9]{64}', self.profile_sha256):
            raise DeploymentError('CLOUD_PROFILE_DIGEST_INVALID')
        checks = (
            integer(self.version, 1, 1),
            integer(self.budget_micro_usd, 0, 1_000_000_000),
            integer(self.model_context_tokens, OUTPUT_TOKEN_LIMIT, 10_000_000),
            integer(self.input_micro_usd_per_million_tokens, 1, 1_000_000_000),
            integer(self.output_micro_usd_per_million_tokens, 1, 1_000_000_000),
            integer(self.created_at_us, 1, 9_000_000_000_000_000),
            integer(self.expires_at_us, 1, 9_000_000_000_000_000),
        )
        if not all(checks):
            raise DeploymentError('CLOUD_POLICY_INVALID')
        if not self.created_at_us < self.expires_at_us <= self.created_at_us + DAY_US:
            raise DeploymentError('CLOUD_AUTHORIZATION_WINDOW_INVALID')

    @classmethod
    def parse(cls, raw):
        if type(raw) not in (str, bytes) or len(raw) > 4096:
            raise DeploymentError('CLOUD_POLICY_INVALID')
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise DeploymentError('CLOUD_POLICY_INVALID')
                out[key] = value
            return out
        def constant(_):
            raise DeploymentError('CLOUD_POLICY_INVALID')
        try:
            obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
            if type(obj) is not dict or set(obj) != set(cls.__dataclass_fields__):
                raise DeploymentError('CLOUD_POLICY_FIELDS_INVALID')
            return cls(**obj)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise DeploymentError('CLOUD_POLICY_INVALID') from None

    def public(self):
        return asdict(self)

    @property
    def digest(self):
        return digest(self.public())

    @property
    def reserve_micro_usd(self):
        # Reserve the FULL declared context window, not an unproved character-to-
        # token estimate. Ignore cached-input discounts. Round UP once, in integers.
        numerator = (self.model_context_tokens * self.input_micro_usd_per_million_tokens
                     + OUTPUT_TOKEN_LIMIT * self.output_micro_usd_per_million_tokens)
        return (numerator + 999_999) // 1_000_000

    def validate_profile(self, profile):
        Profile.parse(canonical(profile.public()))
        if (profile.provider != 'openai-chat-json' or profile.local_port is not None
                or profile.version != 3
                or profile.response_contract != 'chronos.preference-extraction.v1'):
            raise DeploymentError('CLOUD_E1_PROFILE_REQUIRED')
        if profile.digest != self.profile_sha256:
            raise DeploymentError('CLOUD_PROFILE_MISMATCH')
        # Exact reviewed current IDs need not have a date suffix. Dated IDs remain
        # valid at the ledger layer, not evidence of endpoint compatibility; the
        # public launcher separately requires reviewed_model(). No substitution.
        if profile.model not in MODELS and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*-\d{4}-\d{2}-\d{2}', profile.model):
            raise DeploymentError('CLOUD_PINNED_MODEL_REQUIRED')

    def validate_authorization(self, authorized_policy_sha256, now_us, deadline_us):
        if type(authorized_policy_sha256) is not str or authorized_policy_sha256 != self.digest:
            raise DeploymentError('CLOUD_EXPLICIT_BUDGET_AUTHORIZATION_REQUIRED')
        if not self.created_at_us <= now_us < self.expires_at_us:
            raise DeploymentError('CLOUD_AUTHORIZATION_NOT_CURRENT')
        if (type(deadline_us) is not int or not now_us < deadline_us <= now_us + 30_000_000
                or deadline_us > self.expires_at_us):
            raise DeploymentError('CLOUD_DEADLINE_INVALID')


class CloudAllowance:
    """One immutable profile/policy; atomic monetary AND request reservation.

    create() requires the exact approved policy digest; claim() requires it again.
    A digest scopes consent but cannot prove a human granted it. Caller/operator
    owns that approval boundary. Never reset/recreate this file to renew funding.
    Database ownership is a deployment responsibility; filesystem administrators
    can alter state or make additional files and are outside this boundary.
    """
    def __init__(self, path, profile, policy):
        self.path = Path(path).resolve()
        self.profile = Profile.parse(canonical(profile.public()))
        self.policy = CloudBudgetPolicy.parse(canonical(policy.public()))
        self.policy.validate_profile(self.profile)
        with self._connect() as db:
            self._bindings(db)
            self._totals(db)

    @classmethod
    def create(cls, path, profile, policy, *, authorized_policy_sha256):
        profile = Profile.parse(canonical(profile.public()))
        policy = CloudBudgetPolicy.parse(canonical(policy.public()))
        policy.validate_profile(profile)
        if type(authorized_policy_sha256) is not str or authorized_policy_sha256 != policy.digest:
            raise DeploymentError('CLOUD_EXPLICIT_BUDGET_AUTHORIZATION_REQUIRED')
        path = Path(path).resolve()
        try:
            with path.open('xb'):
                pass
        except FileExistsError:
            raise DeploymentError('CLOUD_ALLOWANCE_ALREADY_EXISTS') from None
        # Preserve any incomplete file on failure. Opening it never repairs it.
        try:
            with closing(sqlite3.connect(path, timeout=2)) as db, db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1), profile TEXT NOT NULL, policy TEXT NOT NULL)')
                db.execute('CREATE TABLE control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), halted TEXT NOT NULL)')
                db.execute("INSERT INTO control VALUES (1,'')")
                db.execute('CREATE TABLE claims (request_id TEXT PRIMARY KEY, body_digest TEXT NOT NULL, at_us INTEGER NOT NULL, outcome TEXT NOT NULL, reserved_micro_usd INTEGER NOT NULL)')
                db.execute('INSERT INTO binding VALUES (1,?,?)', (canonical(profile.public()), canonical(policy.public())))
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None
        return cls(path, profile, policy)

    def _connect(self):
        try:
            return closing(sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=2))
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None

    def _bindings(self, db):
        try:
            rows = db.execute('SELECT singleton,profile,policy FROM binding').fetchall()
            control = db.execute('SELECT singleton,halted FROM control').fetchall()
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None
        if len(control) != 1 or control[0][0] != 1 or control[0][1] not in ('', 'UNEXPECTED_PROVIDER_TIER', 'PROVIDER_USAGE_OUTSIDE_AUTHORIZED_LIMIT'):
            raise DeploymentError('CLOUD_ALLOWANCE_INCONSISTENT')
        if rows != [(1, canonical(self.profile.public()), canonical(self.policy.public()))]:
            raise DeploymentError('CLOUD_BINDING_MISMATCH')

    def _totals(self, db):
        try:
            rows = db.execute('SELECT outcome,reserved_micro_usd,COUNT(*) FROM claims GROUP BY outcome,reserved_micro_usd').fetchall()
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None
        counts = {}
        for outcome, reserve, count in rows:
            if outcome not in ('IN_FLIGHT', 'VERIFIED_STOP', 'FAILED', 'UNCERTAIN') or reserve != self.policy.reserve_micro_usd:
                raise DeploymentError('CLOUD_ALLOWANCE_INCONSISTENT')
            counts[outcome] = count
        used = sum(counts.values())
        reserved = used * self.policy.reserve_micro_usd
        if used > self.profile.request_limit or reserved > self.policy.budget_micro_usd:
            raise DeploymentError('CLOUD_ALLOWANCE_INCONSISTENT')
        return used, reserved, counts

    def claim(self, request_id, body_digest, deadline_us, *, authorized_policy_sha256):
        if type(request_id) is not str or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', request_id):
            raise DeploymentError('INVALID_REQUEST_ID')
        if type(body_digest) is not str or not re.fullmatch(r'[a-f0-9]{64}', body_digest):
            raise DeploymentError('INVALID_BODY_DIGEST')
        try:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    self._bindings(db)
                    # Check AFTER the writer lock. Expired waiting requests spend zero.
                    now = time.time_ns() // 1000
                    if db.execute('SELECT halted FROM control WHERE singleton=1').fetchone()[0]:
                        raise DeploymentError('CLOUD_ALLOWANCE_HALTED')
                    self.policy.validate_authorization(authorized_policy_sha256, now, deadline_us)
                    if db.execute('SELECT 1 FROM claims WHERE request_id=?', (request_id,)).fetchone():
                        raise DeploymentError('REQUEST_ALREADY_USED')
                    used, reserved, _ = self._totals(db)
                    if used >= self.profile.request_limit:
                        raise DeploymentError('REQUEST_LIMIT_REACHED')
                    if reserved + self.policy.reserve_micro_usd > self.policy.budget_micro_usd:
                        raise DeploymentError('CLOUD_BUDGET_EXHAUSTED')
                    db.execute('INSERT INTO claims VALUES (?,?,?,?,?)', (request_id, body_digest, now, 'IN_FLIGHT', self.policy.reserve_micro_usd))
                    db.commit()
                    return {'claimed': True, 'request_id': request_id,
                            'profile_sha256': self.profile.digest, 'policy_sha256': self.policy.digest,
                            'reserved_micro_usd': self.policy.reserve_micro_usd}
                except Exception:
                    db.rollback()
                    raise
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None

    def finish(self, request_id, outcome):
        if type(outcome) is not str or outcome not in ('VERIFIED_STOP', 'FAILED', 'UNCERTAIN'):
            raise DeploymentError('INVALID_OUTCOME')
        try:
            with self._connect() as db, db:
                self._bindings(db)
                if db.execute('SELECT 1 FROM claims WHERE request_id=?', (request_id,)).fetchone() is None:
                    raise DeploymentError('REQUEST_NOT_CLAIMED')
                # No refund, including pre-dispatch failure or a later success.
                db.execute("UPDATE claims SET outcome=? WHERE request_id=? AND outcome='IN_FLIGHT'", (outcome, request_id))
                return db.execute('SELECT outcome FROM claims WHERE request_id=?', (request_id,)).fetchone()[0]
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None

    def check_dispatch(self, request_id, body_digest, deadline_us, *, authorized_policy_sha256):
        """Fresh read immediately before sending; no network under a transaction.

        A halt committed after this admission cannot revoke already admitted I/O.
        A failed check never refunds the original durable reservation.
        """
        try:
            with self._connect() as db:
                db.execute('BEGIN')
                self._bindings(db)
                if db.execute('SELECT halted FROM control WHERE singleton=1').fetchone()[0]:
                    raise DeploymentError('CLOUD_ALLOWANCE_HALTED')
                row = db.execute('SELECT body_digest,outcome FROM claims WHERE request_id=?', (request_id,)).fetchone()
                if row != (body_digest, 'IN_FLIGHT'):
                    raise DeploymentError('CLOUD_RESERVATION_NOT_PENDING')
                self.policy.validate_authorization(authorized_policy_sha256, time.time_ns() // 1000, deadline_us)
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None

    def halt(self, reason):
        if reason not in ('UNEXPECTED_PROVIDER_TIER', 'PROVIDER_USAGE_OUTSIDE_AUTHORIZED_LIMIT'):
            raise DeploymentError('INVALID_HALT_REASON')
        try:
            with self._connect() as db, db:
                self._bindings(db)
                db.execute("UPDATE control SET halted=? WHERE singleton=1 AND halted=''", (reason,))
        except sqlite3.Error:
            raise DeploymentError('CLOUD_ALLOWANCE_UNAVAILABLE') from None

    def snapshot(self):
        with self._connect() as db:
            db.execute('BEGIN')
            self._bindings(db)
            used, reserved, counts = self._totals(db)
            halted = db.execute('SELECT halted FROM control WHERE singleton=1').fetchone()[0]
        return {'profile_sha256': self.profile.digest, 'policy_sha256': self.policy.digest,
                'used': used, 'remaining_requests': self.profile.request_limit - used,
                'reserved_micro_usd': reserved,
                'remaining_budget_micro_usd': self.policy.budget_micro_usd - reserved,
                'reserve_per_request_micro_usd': self.policy.reserve_micro_usd,
                'outcomes': counts, 'halted': halted or None, 'billing_verified': False, 'ready': False}
