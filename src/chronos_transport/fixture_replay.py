"""Closed jury-fixture replay, not a general agent or fresh model inference.

Only the four shipped first_case definitions and four self-contained English
questions below are admitted. E1 business facts, original receipt and fresh
trials are checked against that fixed bank before any capture can be reused.
Native freshness, authentication, approval and effect checks remain mandatory.
Hashes pin supplied evidence; they do not prove that a model actually ran.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import ast
import json
import os
import re
import stat

from . import replay
from chronos_agent import contract
from chronos_simulation import clock
from chronos_simulation.store import Destinations

MODE = 'RECORDED_FIXTURE'
MODEL = 'chronos-recorded-fixture-v1'
SCHEMA = 'chronos.fixture-replay-corpus.v1'
ReplayError = replay.ReplayError
ReplayResult = replay.ReplayResult
E1, C2 = replay.E1, replay.C2
CASE_RULES = (
    ('economy', 'CHEAPEST_ON_TIME', 'PREFERENCE_MATCH'),
    ('earliest', 'EARLIEST_ALLOWED', 'PREFERENCE_MATCH'),
    ('ambiguous', 'UNRESOLVED', 'CONTEXT_AMBIGUOUS'),
    ('queue_inventory', 'CHEAPEST_ON_TIME', 'PREFERENCE_MATCH'),
)
# Required subjects and allowed subjects are fixed per self-contained question.
# Recorded plans are retained; this module never synthesizes an answer or plan.
QUESTION_RULES = (
    ('Why was this option recommended?', ('DECISION',),
     ('DECISION', 'COMPARISON', 'CURRENT_REVIEW', 'DESTINATION_SIMULATION')),
    ('What is the current operation status?', ('OPERATION_STATUS',),
     ('OPERATION_STATUS', 'DESTINATION_SIMULATION', 'CURRENT_REVIEW')),
    ('Does acceptance prove physical delivery?', ('PHYSICAL_DELIVERY',),
     ('OPERATION_STATUS', 'PHYSICAL_DELIVERY')),
    ('What can I do next?', (),
     ('CURRENT_REVIEW', 'APPROVAL_REQUIREMENTS', 'OPERATION_STATUS')),
)
QUESTIONS = tuple(item[0] for item in QUESTION_RULES)
_need, canonical, digest = replay._need, replay.canonical, replay.digest


def _source():
    """Read the fixed installed fixture source, never a path from a request."""
    path = Path(__file__).resolve().parents[2] / 'deployment' / 'first_case.py'
    try:
        raw = path.read_bytes()
        _need(0 < len(raw) <= 262144, 'FIXTURE_SOURCE_UNAVAILABLE')
        return path, raw
    except (OSError, ValueError):
        raise ReplayError('FIXTURE_SOURCE_UNAVAILABLE') from None


def _policy():
    return {'schema': 'chronos.fixture-bank.v1', 'cases': CASE_RULES,
            'questions': QUESTION_RULES, 'trial_modes': ['WITH_TRIALS'],
            'history': 'ONLY_BANK_USER_QUESTIONS_AND_CHECKED_ASSISTANT_TEXT',
            'source_interpretation': 'FIXED_PREFERENCE_CUSTOMER_CITATION_REQUIRED',
            'original': 'ONE_SHIPPED_ORIGINAL_A_FINALLY_REJECTED',
            'fresh_inference': False}


def fixture_bank_digest():
    _, raw = _source()
    return sha256(b'chronos.fixture-bank.v1\0' + sha256(raw).digest()
                  + canonical(_policy()).encode('utf-8')).hexdigest()


def _definition(deployment_id, case):
    # Evaluate only the three reviewed fixture definitions. Importing the CLI
    # would change sys.path/bytecode settings; no CLI or top-level I/O is run.
    path, raw = _source()
    try:
        tree = ast.parse(raw, filename=str(path))
        selected = []
        names = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'CASES' for target in node.targets):
                selected.append(node); names.append('CASES')
            elif isinstance(node, ast.FunctionDef) and node.name in ('identifiers', 'definition'):
                _need(not node.decorator_list, 'FIXTURE_SOURCE_UNSUPPORTED')
                selected.append(node); names.append(node.name)
        _need(sorted(names) == ['CASES', 'definition', 'identifiers'], 'FIXTURE_SOURCE_UNSUPPORTED')
        namespace = {'re': re, 'Blocked': ValueError}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
        return namespace['definition'](deployment_id, case)
    except ReplayError:
        raise
    except (SyntaxError, ValueError, TypeError, KeyError, NameError, UnicodeError):
        raise ReplayError('FIXTURE_SOURCE_UNSUPPORTED') from None


def _e1_fixture(input_json):
    wire = replay._e1_wire(input_json)
    match = re.fullmatch(r'jury-([a-f0-9]{32})-(economy|earliest|ambiguous|queue_inventory)', wire['order_id'])
    _need(match is not None, 'REPLAY_UNSUPPORTED')
    deployment_id, case = match.groups()
    _need(wire['shipment_version'] == 1 and wire['state_revision'] == 3
          and wire['policy_revision'] == 1 and wire['utc_origin_us'] % clock.MICROSECONDS == 0,
          'REPLAY_UNSUPPORTED')
    _need(wire['trial_mode'] == 'WITH_TRIALS', 'REPLAY_UNSUPPORTED')
    world = _definition(deployment_id, case)
    native, events = clock.native_definition(world, (), wire['utc_origin_us'])
    observation = {'definition': native, 'calendar': list(events), 'clock': wire['observed_at']}
    facts = contract.public_facts(observation)
    _need(wire['facts'] == facts, 'REPLAY_UNSUPPORTED')
    _need(wire['trial_horizon'] == 30 * clock.NATIVE_SCALE
          and wire['valid_until'] == min(wire['observed_at'] + 30 * clock.MICROSECONDS,
                                        facts['offer_until'], facts['inventory_expires']),
          'REPLAY_UNSUPPORTED')
    order = world['order_id']
    receipt = Destinations._receipt({'operation_id': order + '-original',
        'attempt_id': order + '-original-attempt', 'order_id': order,
        'shipment_version': 1, 'target': 'A'}, {'state': 'NOT_ACCEPTED_FINAL'})
    evidence = {'source_id': 'evidence:' + receipt['receiptId'],
                **{key: receipt[key] for key in ('operationId', 'attemptId', 'target', 'status', 'closedForever')}}
    _need(wire['evidence'] == [evidence], 'REPLAY_UNSUPPORTED')
    trials, available = contract.outcomes(observation, facts, 'WITH_TRIALS')
    _need(bool(available), 'REPLAY_UNSUPPORTED')
    expected_trials = [{'trial_id': 'trial:' + contract.OPTIONS[row['action']],
                        'option_id': contract.OPTIONS[row['action']], 'observations': row} for row in trials]
    # The native simulator uses tuple trace events; JSON necessarily uses arrays.
    _need(canonical(wire['trials']) == canonical(expected_trials), 'REPLAY_UNSUPPORTED')
    catalog = [{'id': key, 'kind': 'fact'} for key in ('fact:order', 'fact:policy', 'option:A', 'option:B')]
    catalog += [{'id': 'customer-preference', 'kind': 'message'},
                {'id': evidence['source_id'], 'kind': 'evidence'}]
    catalog += [{'id': row['trial_id'], 'kind': 'trial'} for row in expected_trials]
    _need(wire['source_catalog'] == catalog, 'REPLAY_UNSUPPORTED')
    return case, wire


def _c2_fixture(input_json):
    wire = replay._c2_wire(input_json)
    _need(wire['message'] in QUESTIONS, 'REPLAY_UNSUPPORTED')
    # These literal questions are self-contained; a prior user instruction or
    # reference outside this bank is not silently ignored or summarized.
    _need(all(item['role'] != 'user' or item['text'] in QUESTIONS for item in wire['history']),
          'REPLAY_UNSUPPORTED')
    return wire['message'], wire


def project(response_contract, input_json, system_prompt_sha256):
    _need(type(response_contract) is str and response_contract in (E1, C2)
          and replay._hash(system_prompt_sha256), 'REPLAY_INPUT_CONTRACT')
    if response_contract == E1:
        case, _ = _e1_fixture(input_json)
        selector = {'projection': 'chronos.fixture.e1.v1', 'case': case}
    else:
        question, _ = _c2_fixture(input_json)
        selector = {'projection': 'chronos.fixture.c2.v1', 'question': question}
    return {'response_contract': response_contract,
            'system_prompt_sha256': system_prompt_sha256,
            'fixture_sha256': fixture_bank_digest(), **selector}


def projection_key(response_contract, input_json, system_prompt_sha256):
    return digest(project(response_contract, input_json, system_prompt_sha256))


def _answer(contract_name, input_json, response_text):
    response = replay._response(contract_name, input_json, response_text)
    if contract_name == E1:
        case, _ = _e1_fixture(input_json)
        _, preference, reason = next(item for item in CASE_RULES if item[0] == case)
        _need(response['interpreted_preference'] == preference and response['reason_code'] == reason,
              'FIXTURE_INTERPRETATION_MISMATCH')
        _need('customer-preference' in response['source_ids'], 'FIXTURE_CUSTOMER_CITATION_REQUIRED')
    else:
        question, _ = _c2_fixture(input_json)
        _, required, permitted = next(item for item in QUESTION_RULES if item[0] == question)
        topics = set(response['topics'])
        _need(response['preference'] is None and set(required) <= topics <= set(permitted),
              'FIXTURE_QUESTION_PLAN_MISMATCH')
        if question == 'What can I do next?':
            _need(bool(topics & {'CURRENT_REVIEW', 'APPROVAL_REQUIREMENTS'}),
                  'FIXTURE_QUESTION_PLAN_MISMATCH')
    return response


@dataclass(frozen=True)
class _Capture:
    record_id: str
    contract: str
    key: str
    response_text: str
    provenance_json: str


@dataclass(frozen=True)
class FixtureCorpus:
    sha256: str
    fixture_sha256: str
    records: tuple

    @classmethod
    def from_bytes(cls, raw, *, expected_sha256, fixture_sha256, allowed_evidence, allow_synthetic=False):
        _need(type(raw) is bytes and 0 < len(raw) <= replay.MAX_CORPUS_BYTES, 'REPLAY_CORPUS_SIZE')
        _need(replay._hash(expected_sha256) and sha256(raw).hexdigest() == expected_sha256,
              'REPLAY_CORPUS_CHANGED')
        _need(replay._hash(fixture_sha256) and fixture_sha256 == fixture_bank_digest(), 'FIXTURE_BANK_CHANGED')
        _need(type(allowed_evidence) is dict and bool(allowed_evidence)
              and all(replay._hash(key) and replay._text(value, 128) for key, value in allowed_evidence.items()),
              'REPLAY_PROVENANCE_ALLOWLIST_REQUIRED')
        _need(type(allow_synthetic) is bool, 'REPLAY_INVALID_POLICY')
        try:
            body = replay._json(raw.decode('utf-8'), replay.MAX_CORPUS_BYTES)
        except UnicodeError:
            raise ReplayError('REPLAY_INVALID_JSON') from None
        replay._exact(body, {'schema', 'mode', 'fixture_sha256', 'records'}, 'REPLAY_CORPUS_SHAPE')
        _need(body['schema'] == SCHEMA and body['mode'] == MODE
              and body['fixture_sha256'] == fixture_sha256, 'REPLAY_CORPUS_CONTRACT')
        _need(type(body['records']) is list and 1 <= len(body['records']) <= replay.MAX_RECORDS,
              'REPLAY_CORPUS_RECORD_LIMIT')
        records, ids, keys = [], set(), set()
        for item in body['records']:
            replay._exact(item, {'record_id', 'response_contract', 'system_prompt_sha256', 'input_json',
                'response_text', 'projection_sha256', 'provenance'}, 'REPLAY_RECORD_SHAPE')
            ident, name = item['record_id'], item['response_contract']
            _need(type(ident) is str and replay._ID.fullmatch(ident) and ident not in ids, 'REPLAY_RECORD_ID')
            key = projection_key(name, item['input_json'], item['system_prompt_sha256'])
            _need(item['projection_sha256'] == key and key not in keys, 'REPLAY_DUPLICATE_OR_CHANGED_KEY')
            _answer(name, item['input_json'], item['response_text'])
            provenance = item['provenance']
            replay._exact(provenance, {'kind', 'source_model', 'captured_at', 'evidence_sha256',
                'input_sha256', 'response_sha256'}, 'REPLAY_PROVENANCE_SHAPE')
            _need(provenance['kind'] == 'REAL_MODEL_CAPTURE'
                  or (allow_synthetic and provenance['kind'] == 'SYNTHETIC_TEST_ONLY'),
                  'REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE')
            source, evidence = provenance['source_model'], provenance['evidence_sha256']
            _need(type(source) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}', source)
                  and source not in (MODEL, replay.MODEL), 'REPLAY_SOURCE_MODEL')
            _need(replay._hash(evidence) and allowed_evidence.get(evidence) == source,
                  'REPLAY_PROVENANCE_NOT_ALLOWED')
            _need(provenance['input_sha256'] == sha256(item['input_json'].encode('utf-8')).hexdigest()
                  and provenance['response_sha256'] == sha256(item['response_text'].encode('utf-8')).hexdigest(),
                  'REPLAY_CAPTURE_CHANGED')
            try:
                date = provenance['captured_at']
                _need(type(date) is str and len(date) <= 40, 'REPLAY_CAPTURE_DATE')
                stamp = datetime.fromisoformat(date.replace('Z', '+00:00'))
                _need(stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0), 'REPLAY_CAPTURE_DATE')
            except (ValueError, OverflowError):
                raise ReplayError('REPLAY_CAPTURE_DATE') from None
            records.append(_Capture(ident, name, key, item['response_text'], canonical(provenance)))
            ids.add(ident); keys.add(key)
        return cls(expected_sha256, fixture_sha256, tuple(records))

    @classmethod
    def load(cls, path, *, expected_sha256, fixture_sha256, allowed_evidence, allow_synthetic=False):
        try:
            path = Path(path).absolute()
            for part in (*reversed(path.parents), path):
                info = part.lstat()
                _need(not stat.S_ISLNK(info.st_mode)
                      and not getattr(info, 'st_file_attributes', 0) & 0x400, 'REPLAY_CORPUS_PATH')
            before = path.lstat()
            _need(stat.S_ISREG(before.st_mode), 'REPLAY_CORPUS_PATH')
            _need(0 < before.st_size <= replay.MAX_CORPUS_BYTES, 'REPLAY_CORPUS_SIZE')
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                _need((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'REPLAY_CORPUS_PATH_CHANGED')
                raw = stream.read(replay.MAX_CORPUS_BYTES + 1)
                after = os.fstat(stream.fileno())
            current = path.lstat()
            def identity(info):
                return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
            _need(identity(before) == identity(after) == identity(current), 'REPLAY_CORPUS_PATH_CHANGED')
        except ReplayError:
            raise
        except (OSError, ValueError, TypeError):
            raise ReplayError('REPLAY_CORPUS_UNAVAILABLE') from None
        return cls.from_bytes(raw, expected_sha256=expected_sha256, fixture_sha256=fixture_sha256,
                              allowed_evidence=allowed_evidence, allow_synthetic=allow_synthetic)

    def lookup(self, response_contract, input_json, system_prompt_sha256):
        _need(self.fixture_sha256 == fixture_bank_digest(), 'FIXTURE_BANK_CHANGED')
        projection = project(response_contract, input_json, system_prompt_sha256)
        key = digest(projection)
        records = [item for item in self.records if item.contract == response_contract and item.key == key]
        _need(len(records) == 1, 'REPLAY_UNSUPPORTED')
        item = records[0]
        response_text, rebound = item.response_text, []
        if response_contract == C2:
            _, current = _c2_fixture(input_json)
            response = replay._json(response_text, replay.MAX_RESPONSE_BYTES)
            for field in replay.REBIND_FIELDS:
                response[field] = current[field]
            response_text, rebound = canonical(response), list(replay.REBIND_FIELDS)
        _answer(response_contract, input_json, response_text)
        provenance = json.loads(item.provenance_json)
        metadata = {'mode': MODE, 'fresh_inference': False, 'dispatch_authorized': False,
            'corpus_sha256': self.sha256, 'fixture_sha256': self.fixture_sha256,
            'record_id': item.record_id, 'projection': projection['projection'],
            'projection_sha256': key, 'source_model': provenance['source_model'],
            'provenance_kind': provenance['kind'], 'captured_at': provenance['captured_at'],
            'evidence_sha256': provenance['evidence_sha256'],
            'recorded_response_sha256': provenance['response_sha256'], 'rebound_fields': rebound,
            'evidence_binding': 'ALLOWLIST_MATCH_NOT_RUNTIME_PROOF',
            'scope': 'CLOSED_SHIPPED_FIXTURES_AND_NEUTRAL_QUESTIONS_ONLY'}
        return ReplayResult(response_text, canonical(metadata))
