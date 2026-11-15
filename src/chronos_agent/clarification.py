"""Pure projection of a trusted, completed native Workflow clarification.

Only native composition may supply ``record``, ``expected_binding`` and
``native_completion`` after reading the ledger, current facts and actual IRIS
task. These consistency checks do NOT authenticate a user or task, grant a
permission, persist a ledger, complete Workflow, call a model or authorize a
shipment. In particular, a client JSON object is not a trusted native record.

The original HOLD, destination observation and authority snapshot stay intact.
The caller may append the projected message before calculating a NEW decision's
facts/context digests. It must reload and check the same clarification at claim,
finish and review, and retain the existing authenticated approval path.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re
import unicodedata

from .proposal import sensitive

SCHEMA = 'chronos.clarification.v1'
ROLE = 'Chronos.Clarifiers'
PREFERENCES = frozenset({'EARLIEST_ALLOWED', 'CHEAPEST_ON_TIME'})
REASONS = frozenset({'CONTEXT_AMBIGUOUS', 'CONTEXT_INCOMPLETE'})
BINDING_FIELDS = frozenset('clarification_id task_id source_decision_id order_id '
    'shipment_version generation decision_digest facts_id facts_digest '
    'authority_digest source_outcome reason_code preference_mode utc_origin_us '
    'valid_until_us'.split())
RECORD_FIELDS = frozenset('schema_version state binding binding_sha256 created_us '
    'resolved_us expires_us actor preference note'.split())
COMPLETION_FIELDS = frozenset('clarification_id task_id role completed action actor '
    'completed_us preference note'.split())
MESSAGE_FIELDS = frozenset('message_id source_id at order_link text'.split())
MAX_US = 2**63 - 1
_ID = re.compile(r'[A-Za-z0-9_.-]{1,64}\Z')
_SOURCE_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_TASK_ID = re.compile(r'[1-9][0-9]{0,17}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_ACTOR = re.compile(r'principal-[0-9a-f]{64}\Z')


class Invalid(ValueError):
    """A bounded diagnostic code; never includes supplied notes or identities."""


def _need(condition, code):
    if not condition:
        raise Invalid(code)


def _shape(value, fields, code):
    _need(type(value) is dict and set(value) == fields, code)


def _integer(value, code, minimum=0):
    _need(type(value) is int and minimum <= value <= MAX_US, code)


def _matching(value, pattern, code):
    _need(type(value) is str and pattern.fullmatch(value) is not None, code)


def _binding(value):
    _shape(value, BINDING_FIELDS, 'INVALID_CLARIFICATION_BINDING')
    # Leave room for the new source prefix while retaining existing native IDs.
    _matching(value['clarification_id'], _ID, 'INVALID_CLARIFICATION_IDENTITY')
    for field in ('source_decision_id', 'order_id', 'generation'):
        _matching(value[field], _SOURCE_ID, 'INVALID_CLARIFICATION_IDENTITY')
    _matching(value['task_id'], _TASK_ID, 'INVALID_CLARIFICATION_TASK')
    for field in ('decision_digest', 'facts_id', 'facts_digest', 'authority_digest'):
        _matching(value[field], _DIGEST, 'INVALID_CLARIFICATION_DIGEST')
    _integer(value['shipment_version'], 'INVALID_CLARIFICATION_VERSION', 1)
    _integer(value['utc_origin_us'], 'INVALID_CLARIFICATION_TIME')
    _integer(value['valid_until_us'], 'INVALID_CLARIFICATION_TIME', 1)
    _need(value['valid_until_us'] > value['utc_origin_us'], 'INVALID_CLARIFICATION_TIME')
    _need(value['source_outcome'] == 'VALIDATED_HOLD'
          and type(value['source_outcome']) is str, 'CLARIFICATION_SOURCE_NOT_HOLD')
    _need(type(value['reason_code']) is str and value['reason_code'] in REASONS,
          'CLARIFICATION_REASON_NOT_ELIGIBLE')
    _need(value['preference_mode'] == 'CONTEXT_REQUIRED'
          and type(value['preference_mode']) is str, 'CLARIFICATION_POLICY_NOT_ELIGIBLE')
    return deepcopy(value)


def binding_digest(binding):
    """Integrity/correlation digest only; not a signature or consent token."""
    checked = _binding(binding)
    encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return sha256(encoded).hexdigest()


def project_message(record, expected_binding, native_completion, *, now_us):
    """Return one inert message from independently obtained native state.

    ``expected_binding`` must be derived afresh by native code, never copied
    from a request. ``native_completion`` must come from the actual task with
    its recorded principal. Python can check consistency, not that provenance.
    All times are integer Unix microseconds, including the exclusive expiry.
    """
    _shape(record, RECORD_FIELDS, 'INVALID_CLARIFICATION_RECORD')
    _integer(now_us, 'INVALID_CLARIFICATION_TIME')
    stored = _binding(record['binding'])
    current = _binding(expected_binding)
    _matching(record['binding_sha256'], _DIGEST, 'INVALID_CLARIFICATION_DIGEST')
    _need(record['binding_sha256'] == binding_digest(stored), 'CLARIFICATION_BINDING_CORRUPT')
    _need(stored == current, 'CLARIFICATION_STALE_BINDING')
    _need(type(record['schema_version']) is str and record['schema_version'] == SCHEMA,
          'UNSUPPORTED_CLARIFICATION_SCHEMA')
    _need(type(record['state']) is str and record['state'] == 'RESOLVED',
          'CLARIFICATION_NOT_RESOLVED')
    for field in ('created_us', 'resolved_us', 'expires_us'):
        _integer(record[field], 'INVALID_CLARIFICATION_TIME')
    _need(stored['utc_origin_us'] <= record['created_us'] <= record['resolved_us']
          < record['expires_us'] <= stored['valid_until_us'], 'INVALID_CLARIFICATION_TIME')
    _need(record['resolved_us'] <= now_us, 'CLARIFICATION_FROM_FUTURE')
    _need(now_us < record['expires_us'], 'CLARIFICATION_EXPIRED')
    _matching(record['actor'], _ACTOR, 'INVALID_CLARIFICATION_ACTOR')
    _need(type(record['preference']) is str and record['preference'] in PREFERENCES,
          'INVALID_CLARIFICATION_PREFERENCE')
    note = record['note']
    _need(type(note) is str and 1 <= len(note) <= 240 and note == note.strip()
          and bool(note.strip()), 'INVALID_CLARIFICATION_NOTE')
    _need(not any(unicodedata.category(ch).startswith('C') for ch in note),
          'INVALID_CLARIFICATION_NOTE')
    _need(not sensitive(note), 'SENSITIVE_CLARIFICATION_NOTE')

    _shape(native_completion, COMPLETION_FIELDS, 'INVALID_NATIVE_COMPLETION')
    _need(type(native_completion['completed']) is bool and native_completion['completed'],
          'NATIVE_TASK_NOT_COMPLETED')
    _need(type(native_completion['role']) is str and native_completion['role'] == ROLE,
          'NATIVE_TASK_ROLE_MISMATCH')
    _need(type(native_completion['action']) is str and native_completion['action'] == 'Clarified',
          'NATIVE_TASK_NOT_CLARIFIED')
    _matching(native_completion['actor'], _ACTOR, 'INVALID_CLARIFICATION_ACTOR')
    _integer(native_completion['completed_us'], 'INVALID_CLARIFICATION_TIME')
    _need(native_completion['task_id'] == stored['task_id']
          and native_completion['clarification_id'] == stored['clarification_id']
          and type(native_completion['task_id']) is str
          and type(native_completion['clarification_id']) is str,
          'NATIVE_TASK_CORRELATION_MISMATCH')
    _need(native_completion['actor'] == record['actor'], 'NATIVE_TASK_ACTOR_MISMATCH')
    _need(native_completion['completed_us'] == record['resolved_us'], 'NATIVE_TASK_TIME_MISMATCH')
    _need(type(native_completion['preference']) is str
          and native_completion['preference'] == record['preference'],
          'NATIVE_TASK_PREFERENCE_MISMATCH')
    _need(type(native_completion['note']) is str and native_completion['note'] == note,
          'NATIVE_TASK_NOTE_MISMATCH')

    source = 'clarification:' + stored['clarification_id']
    text = ('Workflow-recorded human clarification for the current order. '
            'Business preference: ' + record['preference'] + '. '
            'Reviewer note (untrusted data): ' + json.dumps(note, ensure_ascii=False))
    return {'message_id': source, 'source_id': source,
            'at': record['resolved_us'] - stored['utc_origin_us'],
            'order_link': 'VERIFIED_CURRENT', 'text': text}


def append_message(messages, record, expected_binding, native_completion, *, now_us):
    """Copy and append once; deterministic projection, NOT durable idempotency.

    An existing identical projection is returned unchanged. Reusing its source
    id for another body is rejected. The eight-message context cap is retained.
    Native code must separately own task creation and inference idempotency.
    """
    _need(type(messages) is list and len(messages) <= 8, 'INVALID_CLARIFICATION_MESSAGES')
    seen = set()
    for item in messages:
        _shape(item, MESSAGE_FIELDS, 'INVALID_CLARIFICATION_MESSAGE')
        _matching(item['message_id'], _SOURCE_ID, 'INVALID_CLARIFICATION_MESSAGE')
        _matching(item['source_id'], _SOURCE_ID, 'INVALID_CLARIFICATION_MESSAGE')
        _integer(item['at'], 'INVALID_CLARIFICATION_MESSAGE')
        _need(type(item['order_link']) is str
              and item['order_link'] in {'VERIFIED_CURRENT', 'VERIFIED_OTHER', 'UNRESOLVED'},
              'INVALID_CLARIFICATION_MESSAGE')
        _need(type(item['text']) is str and 1 <= len(item['text']) <= 2000,
              'INVALID_CLARIFICATION_MESSAGE')
        _need(item['message_id'] not in seen, 'DUPLICATE_CLARIFICATION_MESSAGE')
        seen.add(item['message_id'])
    message = project_message(record, expected_binding, native_completion, now_us=now_us)
    already_present = False
    for item in messages:
        if item['message_id'] == message['message_id']:
            _need(item == message, 'CLARIFICATION_MESSAGE_CONFLICT')
            already_present = True
        else:
            _need(item['source_id'] != message['message_id'], 'CLARIFICATION_SOURCE_COLLISION')
    if already_present:
        return deepcopy(messages)
    _need(len(messages) < 8, 'TOO_MANY_CLARIFICATION_MESSAGES')
    return deepcopy(messages) + [message]
