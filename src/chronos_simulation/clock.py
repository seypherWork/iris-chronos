"""One conversion boundary: scenario minutes, native microseconds, IRIS UTC.

The native simulator has 1 microsecond resolution, matching the declared lab
model; this is not a claim of infinitely precise physical timing.
"""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import time

from .model import Blocked, canonical, clock_scale, integer, validate

MICROSECONDS=1_000_000
NATIVE_SCALE=60*MICROSECONDS
IRIS_UNIX_OFFSET=int((datetime(1970,1,1)-datetime(1840,12,31)).total_seconds())


def now_us():return time.time_ns()//1000


def iris_utc_to_us(value):
    """Floor expirations conservatively; never subtract large epochs as floats."""
    if type(value) not in (int,float,str,Decimal):raise Blocked('invalid_iris_utc')
    try:stamp=Decimal(str(value))
    except Exception as exc:raise Blocked('invalid_iris_utc') from exc
    if not stamp.is_finite() or stamp<IRIS_UNIX_OFFSET:raise Blocked('invalid_iris_utc')
    return int(((stamp-IRIS_UNIX_OFFSET)*MICROSECONDS).to_integral_value(rounding=ROUND_FLOOR))


def native_definition(world, changes, origin_us):
    """Trusted registration only. Original minute fixtures remain unchanged."""
    import json
    if any(k in world for k in ('clock_ticks_per_minute','utc_origin_us','offer_until_us')):
        raise Blocked('clock_metadata_is_installer_owned')
    validate(world)
    changes=tuple(changes)
    for c in changes:c.validate()
    integer(origin_us,'utc_origin_us')
    origin_us=(origin_us//MICROSECONDS)*MICROSECONDS
    new=json.loads(canonical(world))
    new.update(clock_ticks_per_minute=NATIVE_SCALE,utc_origin_us=origin_us,
               offer_until_us=origin_us+30*NATIVE_SCALE)
    events=tuple(replace(c,at=c.at*NATIVE_SCALE,value=c.value*NATIVE_SCALE) for c in changes)
    return new,events


def require_native(world):
    if clock_scale(world)!=NATIVE_SCALE:raise Blocked('native_clock_required')
    for field in ('utc_origin_us','offer_until_us'):integer(world.get(field),field)
    if world['utc_origin_us']%MICROSECONDS or world['offer_until_us']<=world['utc_origin_us']:
        raise Blocked('invalid_native_clock_origin_or_offer')


def authority_snapshot(observation):
    """Stable absolute constraints; refreshing observedAt never renews them."""
    world=observation['definition'];require_native(world)
    origin=world['utc_origin_us']//MICROSECONDS+IRIS_UNIX_OFFSET
    observed=(world['utc_origin_us']+observation['clock'])//MICROSECONDS+IRIS_UNIX_OFFSET
    return {'orderId':world['order_id'],'shipmentVersion':world['shipment_version'],
            'revision':observation['facts_revision'],'policyRevision':1,
            'payload':canonical(world['payload']),'quantity':world['payload']['quantity'],
            'maxCost':world['budget'],'deliveryDeadline':origin+world['deadline']*60,
            'inventoryUntil':origin+world['inventory_expires']*60,'observedAt':observed,
            'offers':{t:{'target':t,'cost':o['cost'],'availableAt':origin+o['available_at']*60,
                          'queueSeconds':o['queue_minutes']*60,'travelSeconds':o['travel_minutes']*60,
                          'validUntil':world['offer_until_us']//MICROSECONDS+IRIS_UNIX_OFFSET,
                          'capacity':world['payload']['quantity']} for t,o in world['options'].items()}}
