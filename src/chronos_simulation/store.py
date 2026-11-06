"""Durable owned A/B simulators using the same engine as isolated trials.

Only trusted scenario/transport callers may invoke this component. No HTTP route,
human authentication, real carrier or IRIS dispatcher is implemented here.
Logical time is explicitly advanced by the lab controller, never by the agent.
"""
from contextlib import contextmanager, closing
from dataclasses import asdict
from pathlib import Path
from copy import deepcopy
import json
import re
import sqlite3
import math
import time

from .model import Blocked, TARGETS, canonical, clock_scale, fingerprint, integer, validate
from .workflow import Change, Workflow, preview

FIELDS = {'operation_id','attempt_id','order_id','shipment_version','target',
          'payload','reserved_at','valid_until'}
ID = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


class Destinations:
    def __init__(self, path, *, existing=False):
        self.path = Path(path)
        if existing:
            # A missing registered destination is an error, never a new empty
            # database whose missing records could be mistaken for rejection.
            with closing(self._connect()) as db:
                self._scenario(db)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS scenario (id INTEGER PRIMARY KEY CHECK(id=1), world TEXT NOT NULL, calendar TEXT NOT NULL, clock INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (target TEXT NOT NULL, operation_id TEXT NOT NULL, binding TEXT NOT NULL, start INTEGER NOT NULL, closed_at INTEGER, result TEXT NOT NULL, PRIMARY KEY(target,operation_id));
                CREATE TABLE IF NOT EXISTS attempts (target TEXT NOT NULL, attempt_id TEXT NOT NULL, operation_id TEXT NOT NULL, PRIMARY KEY(target,attempt_id));
                CREATE TABLE IF NOT EXISTS observations (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, target TEXT, operation_id TEXT, clock INTEGER NOT NULL);
            ''')

    def _connect(self):
        # All subsequent access is rw, not rwc: disappearance must fail closed.
        return sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=5)

    @contextmanager
    def transaction(self, *, write=False):
        with closing(self._connect()) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @contextmanager
    def realtime_transaction(self):
        # A rejected request must not undo elapsed time or an acceptance that
        # the clock just materialized. Roll back only the requested operation.
        deferred=None
        with self.transaction(write=True) as db:
            self._tick(db)
            db.execute('SAVEPOINT requested_operation')
            try:yield db
            except BaseException as exc:
                db.execute('ROLLBACK TO requested_operation')
                deferred=exc
            finally:db.execute('RELEASE requested_operation')
        if deferred is not None:raise deferred

    def initialize(self, world, changes=(), start=0):
        validate(world);integer(start,'start')
        changes=tuple(changes)
        # Validate calendar, event identities, and the common initial clock.
        Workflow(world,'HOLD',start,changes)
        w=canonical(world);calendar=canonical([asdict(c) for c in changes])
        with self.transaction(write=True) as db:
            row=db.execute('SELECT world,calendar FROM scenario WHERE id=1').fetchone()
            if row:
                if row!=(w,calendar):raise Blocked('scenario_already_initialized_differently')
                return
            db.execute('INSERT INTO scenario VALUES (1,?,?,?)',(w,calendar,start))

    @staticmethod
    def _scenario(db):
        row=db.execute('SELECT world,calendar,clock FROM scenario WHERE id=1').fetchone()
        if row is None:raise Blocked('scenario_not_initialized')
        return json.loads(row[0]),tuple(Change(**c) for c in json.loads(row[1])),row[2]

    @staticmethod
    def _binding(attempt):
        if type(attempt) is not dict or set(attempt)!=FIELDS:raise Blocked('invalid_attempt_fields')
        for key in ('operation_id','attempt_id','order_id'):
            if type(attempt[key]) is not str or not ID.fullmatch(attempt[key]):raise Blocked('invalid_identity')
        if type(attempt['target']) is not str or attempt['target'] not in {'A','B'}:raise Blocked('unregistered_target')
        integer(attempt['shipment_version'],'version',1)
        integer(attempt['reserved_at'],'reserved_at');integer(attempt['valid_until'],'valid_until')
        if attempt['valid_until']<=attempt['reserved_at']:raise Blocked('invalid_validity')
        if type(attempt['payload']) is not str or not 0<len(attempt['payload'].encode('utf-8'))<=65536:raise Blocked('invalid_payload')
        return canonical(attempt)

    @staticmethod
    def _lookup(db, attempt, binding):
        row=db.execute('SELECT binding,start,closed_at,result FROM operations WHERE target=? AND operation_id=?',
                       (attempt['target'],attempt['operation_id'])).fetchone()
        if row and row[0]!=binding:raise Blocked('immutable_operation_conflict')
        return row

    @staticmethod
    def _receipt(attempt, result):
        state=result['state'] if result else None
        status=('ACCEPTED' if state in {'ACCEPTED','DELIVERED_SIMULATED'} else
                'NOT_ACCEPTED_FINAL' if state=='NOT_ACCEPTED_FINAL' else 'UNKNOWN')
        value={'operationId':attempt['operation_id'],'attemptId':attempt['attempt_id'],
               'orderId':attempt['order_id'],'shipmentVersion':attempt['shipment_version'],
               'target':attempt['target'],'status':status,
               'reference':attempt['target']+'-'+attempt['operation_id'] if status=='ACCEPTED' else '',
               'closedForever':status=='NOT_ACCEPTED_FINAL'}
        value['receiptId']='r-'+fingerprint(value)
        return value

    @staticmethod
    def _rebuild(world, changes, attempt, start, closed_at, clock):
        action=next(a for a,t in TARGETS.items() if t==attempt['target'])
        if not attempt['reserved_at']<=start<attempt['valid_until']:
            flow=Workflow(world,'HOLD',start)
            flow.action,flow.target=action,attempt['target']
            flow.close('PROPOSAL_EXPIRED_AT_RECEIPT')
        else:
            flow=Workflow(world,action,start,(c for c in changes if c.at>=start),
                          acceptance_until=attempt['valid_until'])
        if closed_at is not None:
            flow.advance(closed_at)
            flow.close('PROVIDER_FINAL_CLOSURE')
        flow.advance(clock)
        return flow

    def submit(self, attempt, *, admission_deadline=None, expected_observation_id=None):
        return self._submit(attempt,admission_deadline=admission_deadline,
                            expected_observation_id=expected_observation_id)

    def submit_realtime(self, attempt, *, expected_revision):
        integer(expected_revision,'expected_revision',1)
        return self._submit(attempt,expected_revision=expected_revision,realtime=True)

    def _submit(self, attempt, *, admission_deadline=None, expected_observation_id=None,
                expected_revision=None,realtime=False):
        # Optional UTC Unix deadline supplied only by the trusted native adapter.
        # Check after obtaining the writer lock, before a first acceptance.
        if admission_deadline is not None and (type(admission_deadline) not in {int,float} or not math.isfinite(admission_deadline)):
            raise Blocked('invalid_admission_deadline')
        if expected_observation_id is not None and (type(expected_observation_id) is not str or not re.fullmatch('[0-9a-f]{64}',expected_observation_id)):
            raise Blocked('invalid_observation_identity')
        attempt=deepcopy(attempt);binding=self._binding(attempt)
        with (self.realtime_transaction() if realtime else self.transaction(write=True)) as db:
            world,changes,clock=self._scenario(db)
            row=self._lookup(db,attempt,binding)
            if row:return self._receipt(attempt,json.loads(row[3]))
            if expected_observation_id is not None and self._observation(db)['observation_id']!=expected_observation_id:
                raise Blocked('stale_destination_observation')
            if (attempt['order_id'],attempt['shipment_version'],attempt['payload'])!=(world['order_id'],world['shipment_version'],canonical(world['payload'])):
                raise Blocked('provider_order_or_payload_mismatch')
            if attempt['reserved_at']>clock:raise Blocked('receipt_precedes_commit')
            if db.execute('SELECT 1 FROM attempts WHERE target=? AND attempt_id=?',(attempt['target'],attempt['attempt_id'])).fetchone():
                raise Blocked('attempt_identity_reused')
            reason=''
            if realtime and expected_revision!=self._observation(db)['facts_revision']:
                reason='SOURCE_FACTS_CHANGED'
            elif admission_deadline is not None and time.time()>=admission_deadline:
                reason='PROPOSAL_EXPIRED_AT_RECEIPT'
            if reason:
                flow=Workflow(world,'HOLD',clock)
                flow.action=next(a for a,t in TARGETS.items() if t==attempt['target'])
                flow.target=attempt['target'];flow.close(reason)
            else:
                flow=self._rebuild(world,changes,attempt,clock,None,clock)
            # A wall-clock rejection is a durable closure too, so rebuilding the
            # workflow later must never turn that rejection into an acceptance.
            closed=clock if flow.state=='NOT_ACCEPTED_FINAL' else None
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?)',(attempt['target'],attempt['operation_id'],binding,clock,closed,canonical(flow.result())))
            db.execute('INSERT INTO attempts VALUES (?,?,?)',(attempt['target'],attempt['attempt_id'],attempt['operation_id']))
            db.execute('INSERT INTO observations(kind,target,operation_id,clock) VALUES (?,?,?,?)',('SUBMIT',attempt['target'],attempt['operation_id'],clock))
            result=self._receipt(attempt,flow.result())
        return result  # Commit is complete before any transport response.

    def query(self, attempt):
        binding=self._binding(attempt)
        with self.transaction() as db:
            self._scenario(db)
            row=self._lookup(db,attempt,binding)
            return self._receipt(attempt,json.loads(row[3]) if row else None)

    def query_identity(self, identity):
        """Readback after a lost dispatch response; never creates an operation."""
        if type(identity) is not dict or set(identity)!=FIELDS-{'reserved_at','valid_until'}:
            raise Blocked('invalid_query_identity')
        self._binding(identity|{'reserved_at':0,'valid_until':1})
        with self.transaction() as db:
            self._scenario(db)
            row=db.execute('SELECT binding,result FROM operations WHERE target=? AND operation_id=?',
                           (identity['target'],identity['operation_id'])).fetchone()
            if row:
                stored=json.loads(row[0])
                if any(stored[k]!=v for k,v in identity.items()):raise Blocked('query_identity_conflict')
            return self._receipt(identity,json.loads(row[1]) if row else None)

    def close_unaccepted(self, attempt):
        """Scenario-owner final rejection only; not a public cancellation API."""
        return self._close(attempt)

    def close_realtime(self, attempt):
        return self._close(attempt,realtime=True)

    def _close(self, attempt, *, realtime=False):
        binding=self._binding(attempt)
        with (self.realtime_transaction() if realtime else self.transaction(write=True)) as db:
            world,changes,clock=self._scenario(db)
            row=self._lookup(db,attempt,binding)
            if row is None:raise Blocked('absence_is_not_final_closure')
            if json.loads(row[3])['state']=='NOT_ACCEPTED_FINAL':
                return self._receipt(attempt,json.loads(row[3]))
            if json.loads(row[3])['state'] in {'ACCEPTED','DELIVERED_SIMULATED'}:
                raise Blocked('cannot_close_accepted')
            flow=self._rebuild(world,changes,attempt,row[1],row[2],clock)
            flow.close('PROVIDER_FINAL_CLOSURE')  # Rejects if already accepted.
            db.execute('UPDATE operations SET closed_at=COALESCE(closed_at,?),result=? WHERE target=? AND operation_id=?',
                       (clock,canonical(flow.result()),attempt['target'],attempt['operation_id']))
            db.execute('INSERT INTO observations(kind,target,operation_id,clock) VALUES (?,?,?,?)',
                       ('CLOSE',attempt['target'],attempt['operation_id'],clock))
            return self._receipt(attempt,flow.result())

    def advance(self, until):
        integer(until,'clock')
        with self.transaction(write=True) as db:
            self._advance(db,until)

    @classmethod
    def _advance(cls, db, until):
        world,changes,clock=cls._scenario(db)
        if until<clock:raise Blocked('clock_cannot_go_backwards')
        if until==clock:return
        changed=False
        for target,operation,binding,start,closed,result in db.execute('SELECT target,operation_id,binding,start,closed_at,result FROM operations').fetchall():
            recorded=json.loads(result)
            if recorded['state']=='NOT_ACCEPTED_FINAL':continue
            if recorded['state'] in {'ACCEPTED','DELIVERED_SIMULATED'}:
                # A new engine version must not revoke durable acceptance.
                # Only the previously committed simulated arrival may advance.
                events=[(c.at,0,c.event_id,'ignored_after_admission:'+c.event_id)
                        for c in changes if clock<c.at<=until and c.target in {'*',target}]
                if recorded['state']=='ACCEPTED' and recorded['arrival']<=until:
                    events.append((recorded['arrival'],1,'','delivered_simulated'))
                    recorded['state']='DELIVERED_SIMULATED'
                for at,_,_,event in sorted(events):recorded['trace'].append([at,event])
                value=canonical(recorded)
            else:
                flow=cls._rebuild(world,changes,json.loads(binding),start,closed,until)
                value=canonical(flow.result())
            if value!=result:
                changed=True
                db.execute('UPDATE operations SET result=? WHERE target=? AND operation_id=?',(value,target,operation))
        db.execute('UPDATE scenario SET clock=? WHERE id=1',(until,))
        if changed:db.execute('INSERT INTO observations(kind,clock) VALUES (?,?)',('TRANSITION',until))
        db.execute('INSERT INTO observations(kind,clock) VALUES (?,?)',('ADVANCE',until))

    @classmethod
    def _tick(cls, db):
        from .clock import now_us,require_native
        world,_,_=cls._scenario(db);require_native(world)
        instant=now_us();integer(instant,'utc_clock')
        elapsed=instant-world['utc_origin_us']
        if elapsed<0:raise Blocked('clock_precedes_scenario')
        cls._advance(db,elapsed)

    def observe_realtime(self):
        # Read time AFTER the writer lock, not before a potentially long wait.
        with self.realtime_transaction() as db:
            return self._observation(db)

    def query_realtime(self, identity):
        if type(identity) is not dict or set(identity)!=FIELDS-{'reserved_at','valid_until'}:
            raise Blocked('invalid_query_identity')
        self._binding(identity|{'reserved_at':0,'valid_until':1})
        with self.realtime_transaction() as db:
            row=db.execute('SELECT binding,result FROM operations WHERE target=? AND operation_id=?',
                           (identity['target'],identity['operation_id'])).fetchone()
            if row:
                stored=json.loads(row[0])
                if any(stored[k]!=v for k,v in identity.items()):raise Blocked('query_identity_conflict')
            return self._receipt(identity,json.loads(row[1]) if row else None)

    def result(self, attempt):
        binding=self._binding(attempt)
        with self.transaction() as db:
            row=self._lookup(db,attempt,binding)
            if not row:raise Blocked('unknown_operation')
            return json.loads(row[3])

    def observe(self):
        """One internal snapshot for execution state and isolated trials.

        The calendar and full definition are trusted controller data, NOT an
        agent prompt. Times are labeled with their explicit logical domain.
        observation_id binds the whole snapshot, including legacy databases
        whose older CLOSE/ADVANCE operations did not have sequence entries.
        """
        with self.transaction() as db:return self._observation(db)

    @classmethod
    def _observation(cls, db):
        world,changes,clock=cls._scenario(db)
        operations=[]
        for binding,result,start,closed in db.execute('SELECT binding,result,start,closed_at FROM operations ORDER BY target,operation_id'):
            attempt=json.loads(binding);result=json.loads(result)
            operations.append({'receipt':cls._receipt(attempt,result),'result':result,
                               'binding':attempt,'start':start,'closed_at':closed})
        sequence=db.execute('SELECT COALESCE(MAX(sequence),0) FROM observations').fetchone()[0]
        revision=world['revision']+db.execute("SELECT COUNT(*) FROM observations WHERE kind IN ('SUBMIT','CLOSE','TRANSITION')").fetchone()[0]
        value={'definition':world,'calendar':[asdict(c) for c in changes],
               'clock':clock,'clock_domain':'LOGICAL_MINUTES' if clock_scale(world)==1 else 'LOGICAL_MICROSECONDS','sequence':sequence,
               'operations':operations}
        value['facts_id']=fingerprint({k:v for k,v in value.items() if k not in {'clock','clock_domain','sequence'}})
        value['facts_revision']=revision
        value['observation_id']=fingerprint(value)
        return value

    @staticmethod
    def _trials_from(observation):
        world=deepcopy(observation['definition']);clock=observation['clock']
        changes=tuple(Change(**c) for c in observation['calendar'])
        states=[op['result']['state'] for op in observation['operations']]
        if any(s in {'ACCEPTED','DELIVERED_SIMULATED'} for s in states):world['original_status']='ACCEPTED'
        elif any(s!='NOT_ACCEPTED_FINAL' for s in states):world['original_status']='UNKNOWN'
        return {a:preview(world,a,clock,(c for c in changes if c.at>=clock)) for a in TARGETS}

    def trial_snapshot(self):
        observation=self.observe()
        return {'observation_id':observation['observation_id'],'sequence':observation['sequence'],
                'clock':observation['clock'],'clock_domain':observation['clock_domain'],
                'trials':self._trials_from(observation)}

    def trials(self):
        return self.trial_snapshot()['trials']

    def inspect(self):
        """Trusted test controller summary, not agent context."""
        with self.transaction() as db:
            _,_,clock=self._scenario(db)
            results=[json.loads(row[0]) for row in db.execute('SELECT result FROM operations')]
            return {'clock':clock,'operations':len(results),
                    'acceptances':sum(r['state'] in {'ACCEPTED','DELIVERED_SIMULATED'} for r in results),
                    'submitted':db.execute("SELECT count(*) FROM observations WHERE kind='SUBMIT'").fetchone()[0]}
