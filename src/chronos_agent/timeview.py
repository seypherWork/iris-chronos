"""Experimental lossless time presentation; no ranking, labels or new authority."""
from copy import deepcopy
from hashlib import sha256
import json

def exact_seconds(microseconds):
    if type(microseconds) is not int:
        raise ValueError('INTEGER_MICROSECONDS_REQUIRED')
    sign = '-' if microseconds < 0 else ''
    whole, fraction = divmod(abs(microseconds), 1000000)
    return sign + str(whole) + (('.' + str(fraction).zfill(6).rstrip('0')) if fraction else '')

def model_input(wire):
    if (wire.get('schema_version') != 'chronos.agent-input.v2'
            or wire.get('clock_kind') != 'relative_microseconds'
            or type(wire.get('ticks_per_minute')) is not int
            or wire['ticks_per_minute'] != 60000000):
        raise ValueError('UNSUPPORTED_TIME_CONTRACT')
    original = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    instants, durations = {}, {}
    def add(target, path, value):
        target[path] = None if value is None else exact_seconds(value)
    for key in ('observed_at', 'valid_until'):
        add(instants, key, wire[key])
    add(durations, 'trial_horizon', wire['trial_horizon'])
    facts = wire['facts']
    for key in ('deadline', 'inventory_expires', 'offer_until'):
        add(instants, 'facts.'+key, facts[key])
    for target, option in facts['options'].items():
        prefix = 'facts.options.'+target+'.'
        add(instants, prefix+'available_at', option['available_at'])
        for key in ('queue_duration', 'travel_duration'):
            add(durations, prefix+key, option[key])
    for group in ('messages', 'known_changes'):
        for index, item in enumerate(facts[group]):
            for key in ('at', 'observed_at'):
                if key in item:
                    add(instants, 'facts.'+group+'['+str(index)+'].'+key, item[key])
    for index, change in enumerate(facts['known_changes']):
        if change.get('kind') != 'DELAY_QUEUE':
            raise ValueError('UNSUPPORTED_CHANGE_KIND')
        add(durations, 'facts.known_changes['+str(index)+'].value', change['value'])
    for index, trial in enumerate(wire['trials']):
        observation = trial['observations']
        for key in ('accepted_at', 'arrival'):
            if key in observation:
                add(instants, 'trials['+str(index)+'].observations.'+key, observation[key])
    envelope = {'schema_version':'chronos.experimental-time-view.v1',
        'context':deepcopy(wire), 'time_view':{
            'source_context_sha256':sha256(original.encode('utf-8')).hexdigest(),
            'unit':'seconds_exact_decimal',
            'instant_origin':'context.utc_origin_us',
            'instants':instants, 'durations':durations}}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
