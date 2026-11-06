"""Shared temporal engine; minute fixtures or explicit native microsecond ticks.
Scenario offer/deadline fields stay in minutes; Change values use clock ticks.
"""
from copy import deepcopy
from dataclasses import dataclass
from .model import Blocked, TARGETS, clock_scale, integer, validate

@dataclass(frozen=True)
class Change:
    event_id: str
    at: int
    kind: str
    target: str
    value: int

    def validate(self):
        if not isinstance(self.event_id, str) or not self.event_id:
            raise Blocked("invalid_event_identity")
        integer(self.at, "event_time")
        integer(self.value, "event_value")
        if self.kind != "DELAY_QUEUE" or self.target not in {"A", "B", "*"}:
            raise Blocked("invalid_change")

class Workflow:
    """One operation, copied facts, explicit transitions and no real-time waiting."""
    def __init__(self, world, action, start=0, changes=(), *, acceptance_until=None):
        validate(world)
        integer(start, "start")
        if acceptance_until is not None:
            integer(acceptance_until, "acceptance_until")
            if acceptance_until <= start:
                raise Blocked("acceptance_deadline_not_after_start")
        self.acceptance_until = acceptance_until
        if action not in {*TARGETS, "HOLD"}:
            raise Blocked("invalid_action")
        self.world = deepcopy(world)
        self.scale = clock_scale(world)
        self.action, self.start, self.clock = action, start, start
        self.target = TARGETS.get(action)
        self.state, self.reason = "QUEUED", ""
        self.accepted_at = self.arrival = None
        self.trace = []
        self.changes, self.event_ids = [], set()
        self.offer = deepcopy(world["options"].get(self.target, {}))
        self.ready_at = max(start, self.offer.get("available_at", 0)*self.scale) + self.offer.get("queue_minutes", 0)*self.scale
        for change in changes:
            self.inject(change)
        if action == "HOLD":
            self.state, self.reason = "HELD", "HUMAN_REVIEW"
            self.trace.append((start, "held"))
        elif world["original_status"] != "NOT_ACCEPTED_FINAL":
            self.state, self.reason = "BLOCKED", "PREVIOUS_ATTEMPT_UNRESOLVED"
            self.trace.append((start, "previous_attempt_unresolved"))
        else:
            self.trace.append((start, "queued"))
        self.advance(start)

    def inject(self, change):
        if not isinstance(change, Change):
            raise Blocked("invalid_change_type")
        change.validate()
        if change.at < self.clock or change.event_id in self.event_ids:
            raise Blocked("past_or_duplicate_change")
        self.event_ids.add(change.event_id)
        self.changes.append(change)
        self.changes.sort(key=lambda item: (item.at, item.event_id))

    def _reject(self, reason):
        self.state, self.reason = "NOT_ACCEPTED_FINAL", reason
        self.trace.append((self.clock, f"rejected:{reason}"))

    def close(self, reason="CLOSED_BEFORE_ACCEPTANCE"):
        if self.state in {"ACCEPTED", "DELIVERED_SIMULATED"}:
            raise Blocked("cannot_close_accepted")
        if self.state == "NOT_ACCEPTED_FINAL":
            return
        self._reject(reason)

    def _change(self, change):
        if change.target not in {"*", self.target}:
            return
        if self.state != "QUEUED":
            self.trace.append((self.clock, f"ignored_after_admission:{change.event_id}"))
            return
        # Additional waiting of this already queued request, not a change to
        # the provider's capacity for all future requests.
        self.ready_at += change.value
        self.trace.append((self.clock, f"change:{change.event_id}"))

    def _admit(self):
        self.trace.append((self.clock, "inventory_checked"))
        if self.scale!=1 and self.clock >= self.world['offer_until_us']-self.world['utc_origin_us']:
            self._reject('OFFER_EXPIRED')
        elif self.clock >= self.world["inventory_expires"]*self.scale:
            self._reject("INVENTORY_EXPIRED")
        elif self.offer["cost"] > self.world["budget"]:
            self._reject("OVER_BUDGET")
        elif self.clock + self.offer["travel_minutes"]*self.scale > self.world["deadline"]*self.scale:
            self._reject("DEADLINE_EXCEEDED")
        else:
            self.accepted_at = self.clock
            self.arrival = self.clock + self.offer["travel_minutes"]*self.scale
            self.state = "ACCEPTED"
            self.world["payload"]["quantity"] = 0
            self.trace.append((self.clock, "accepted"))

    def advance(self, until):
        integer(until, "clock")
        if until < self.clock:
            raise Blocked("clock_cannot_go_backwards")
        while True:
            due = []
            if self.changes:
                due.append(self.changes[0].at)
            if self.state == "QUEUED":
                due.append(self.ready_at)
                if self.acceptance_until is not None:
                    due.append(self.acceptance_until)
            elif self.state == "ACCEPTED":
                due.append(self.arrival)
            if not due or min(due) > until:
                break
            self.clock = min(due)
            # External facts take precedence over admission at the same instant.
            while self.changes and self.changes[0].at == self.clock:
                self._change(self.changes.pop(0))
            # Consent expires before acceptance at the same instant. Accepted
            # work may still finish later: expiration cannot undo acceptance.
            if self.state == "QUEUED" and self.acceptance_until == self.clock:
                self._reject("AUTHORIZATION_EXPIRED_BEFORE_ACCEPTANCE")
            if self.state == "QUEUED" and self.ready_at == self.clock:
                self._admit()
            if self.state == "ACCEPTED" and self.arrival == self.clock:
                self.state = "DELIVERED_SIMULATED"
                self.trace.append((self.clock, "delivered_simulated"))
        self.clock = until
        return self.result()

    def result(self):
        return {"action": self.action, "state": self.state, "reason": self.reason,
                "accepted_at": self.accepted_at, "arrival": self.arrival,
                "cost": self.offer.get("cost"), "trace": tuple(self.trace)}

def preview(world, action, start=0, changes=()):
    return Workflow(world, action, start, changes).advance(start + 30*clock_scale(world))
