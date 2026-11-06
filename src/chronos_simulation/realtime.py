"""Fixed application-facing simulator adapter, internal trusted callers only.

No web route or human authentication. Caller supplies a committed native
operation/ticket; no model output is accepted as dispatch authority here.
The root is deployment configuration and the only destinations are owned A/B.
"""
from copy import deepcopy

from . import clock
from .model import Blocked, canonical, integer
from .registry import Registry
from .store import Destinations


def identity(operation):
    if type(operation) is not dict:raise Blocked('invalid_native_operation')
    try:
        value={'operation_id':operation['operationId'],'attempt_id':operation['attemptId'],
               'order_id':operation['orderId'],'shipment_version':operation['shipmentVersion'],
               'target':operation['target'],'payload':operation['payload']}
    except KeyError as exc:raise Blocked('invalid_native_operation') from exc
    Destinations._binding(value|{'reserved_at':0,'valid_until':1})
    return value


class Runtime:
    def __init__(self,root,*,create=False):self.registry=Registry(root,create=create)

    def register(self,world,changes=()):
        """Installer/scenario owner only. Reopen retains the original epoch."""
        changes=tuple(changes)
        try:existing=self.registry.observe(world['order_id'])
        except Blocked as exc:
            if str(exc)!='order_not_registered':raise
            existing=None
        origin=existing['definition']['utc_origin_us'] if existing else clock.now_us()
        native,events=clock.native_definition(world,changes,origin)
        return self.registry.register(native,events)

    def observe(self,order_id):
        return self.registry._destination(order_id).observe_realtime()

    def snapshot(self,order_id):return clock.authority_snapshot(self.observe(order_id))

    def trials(self,order_id):
        observation=self.observe(order_id)
        return {'observation_id':observation['observation_id'],'facts_id':observation['facts_id'],
                'facts_revision':observation['facts_revision'],'clock':observation['clock'],
                'clock_domain':observation['clock_domain'],
                'snapshot':clock.authority_snapshot(observation),
                'trials':Destinations._trials_from(observation)}

    def submit(self,operation,ticket):
        operation=deepcopy(operation);ticket=deepcopy(ticket)
        ident=identity(operation)
        if type(ticket) is not dict or ticket.get('dispatchGranted') is not True:
            raise Blocked('committed_ticket_required')
        for field in ('operationId','attemptId','target','payload','idempotencyKey','dispatchAt','validUntil'):
            if field not in operation or ticket.get(field)!=operation[field]:
                raise Blocked('ticket_binding_changed')
        if 'reviewDeadlineUS' in operation or 'reviewDeadlineUS' in ticket:
            deadline=operation.get('reviewDeadlineUS')
            integer(deadline,'review_deadline_us',1)
            if type(ticket.get('reviewDeadlineUS')) is not int or ticket['reviewDeadlineUS']!=deadline:
                raise Blocked('human_deadline_binding_changed')
            if ('admittedAt' not in operation or ticket.get('admittedAt')!=operation['admittedAt'] or
                clock.iris_utc_to_us(operation['validUntil'])>deadline or
                clock.iris_utc_to_us(operation['dispatchAt'])>=deadline or
                clock.iris_utc_to_us(operation['admittedAt'])>=deadline):
                raise Blocked('human_deadline_binding_changed')
            # Preserve this expiry in the destination attempt. A late arrival
            # records final non-acceptance, rather than refunding dispatch.
        if operation['idempotencyKey']!=operation['operationId']:raise Blocked('invalid_idempotency_identity')
        integer(operation.get('revision'),'source_revision',1)
        if type(operation.get('policyRevision')) is not int or operation['policyRevision']!=1:
            raise Blocked('unregistered_policy_revision')
        store=self.registry._destination(ident['order_id'])
        world=store.observe()['definition'];clock.require_native(world)
        attempt=ident|{'reserved_at':clock.iris_utc_to_us(operation['dispatchAt'])-world['utc_origin_us'],
                       'valid_until':clock.iris_utc_to_us(operation['validUntil'])-world['utc_origin_us']}
        return store.submit_realtime(attempt,expected_revision=operation['revision'])

    def query(self,operation):
        ident=identity(operation)
        return self.registry._destination(ident['order_id']).query_realtime(ident)
