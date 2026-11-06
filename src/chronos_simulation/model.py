"""Synthetic scenario validation, promoted from offline-01; no real orders."""
import hashlib
import json
TARGETS = {"RETRY_A": "A", "FAILOVER_B": "B"}

class Blocked(ValueError):
    """The proposal cannot cause a new shipment under the observed facts."""

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise Blocked(f"invalid_{label}")
    return value

def clock_scale(world):
    scale=world.get('clock_ticks_per_minute',1)
    if type(scale) is not int or scale not in (1,60_000_000):
        raise Blocked('invalid_clock_scale')
    return scale

def validate(world):
    if not isinstance(world, dict) or not isinstance(world.get("order_id"), str) or not world["order_id"]:
        raise Blocked("invalid_order")
    scale=clock_scale(world)
    if scale!=1:
        for field in ('utc_origin_us','offer_until_us'):integer(world.get(field),field)
        if world['utc_origin_us']%1_000_000 or world['offer_until_us']<=world['utc_origin_us']:
            raise Blocked('invalid_native_clock_origin_or_offer')
    for field in ("shipment_version", "revision"):
        integer(world[field], field, 1)
    for field in ("budget", "deadline", "inventory_expires"):
        integer(world[field], field)
    if world["original_status"] not in {"NOT_ACCEPTED_FINAL", "UNKNOWN", "ACCEPTED", "NOT_FOUND"}:
        raise Blocked("invalid_original_status")
    if world["preference"] not in {"cheapest", "fastest", "context"}:
        raise Blocked("invalid_preference")
    if set(world["options"]) != {"A", "B"}:
        raise Blocked("invalid_targets")
    for option in world["options"].values():
        if set(option) != {"cost", "available_at", "queue_minutes", "travel_minutes"}:
            raise Blocked("invalid_option")
        for key, value in option.items():
            integer(value, key)
    if not isinstance(world["payload"], dict) or not world["payload"]:
        raise Blocked("invalid_payload")
    integer(world["payload"].get("quantity"), "quantity", 1)
    ids = set()
    for message in world["messages"]:
        if (not isinstance(message.get("id"), str) or not message["id"] or
                not isinstance(message.get("text"), str) or message["id"] in ids):
            raise Blocked("invalid_message")
        ids.add(message["id"])
    canonical(world)
