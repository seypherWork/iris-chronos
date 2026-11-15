"""Explicit, finite recorded-fixture transport; never starts a model or IRIS.

Plan is read-only. Prepare creates one new dedicated state and preserves partial
attempts. Status/serve reopen that same state, revalidating its pinned corpus and
fixture bank. This is SDK transport reproduction, not new model inference, native
installation, authentication or permission to submit a recovery.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import sys
from threading import Thread

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'src'
# This launcher is a dedicated short-lived process, not the shared embedded
# Python interpreter. Never import ObjectScript modules or execute callbacks.
if str(SOURCE) not in sys.path:sys.path.insert(0, str(SOURCE))
from chronos_transport.deployment import Profile, Allowance
from chronos_transport import guard

RUNTIME = Path('/opt/chronos/runtime')
MODEL = 'chronos-recorded-fixture-v1'
MODE = 'RECORDED_FIXTURE'
CONTRACTS = {'e1': (3, guard.EXTRACTION_CONTRACT, 'extraction-schema.json', 'fixture-provider', 11512),
             'c2-v2': (6, guard.PLAN_V2_CONTRACT, 'conversation-plan-v2-schema.json', 'fixture-conversation-provider', 11514)}
MAX_CORPUS = 2 * 1024 * 1024


class ProviderError(ValueError):pass


def require(condition, code):
    if not condition:raise ProviderError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def identity(ident):
    require(type(ident) is str and re.fullmatch(r'[a-f0-9]{32}', ident), 'INVALID_DEPLOYMENT_ID')


def contract_spec(contract):
    require(type(contract) is str and contract in CONTRACTS, 'INVALID_REPLAY_CONTRACT')
    return CONTRACTS[contract]


def schema(contract):
    spec = contract_spec(contract)
    value = guard.strict_json((SOURCE / 'chronos_transport' / spec[2]).read_bytes())
    require(guard.response_contract(value) == spec[1], 'WRONG_REPLAY_SCHEMA')
    return value


def plan(ident, limit, corpus_sha256, fixture_sha256, *, contract='e1'):
    """Return the exact public Profile without creating state or allowances."""
    identity(ident)
    version, response_contract, _, _, _ = contract_spec(contract)
    body = dict(version=version, deployment_id=ident, provider='recorded-fixture', model=MODEL,
                schema_sha256=sha256(canonical(schema(contract))).hexdigest(), request_limit=limit,
                local_port=None, reasoning_effort='none', response_contract=response_contract,
                replay_corpus_sha256=corpus_sha256, replay_fixture_sha256=fixture_sha256)
    return Profile.parse(canonical(body)).public()


def plain(path, *, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
            'LINK_OR_REPARSE_POINT')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'WRONG_PATH_KIND')
    return info


def read_plain(path, limit):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'FIXED_ABSOLUTE_PATH_REQUIRED')
    for parent in reversed(path.parents):plain(parent, directory=True)
    info = plain(path)
    require(info.st_size <= limit, 'REPLAY_FILE_LIMIT')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), 'REPLAY_FILE_CHANGED')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = plain(path)
    require(len(raw) <= limit and
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) ==
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns), 'REPLAY_FILE_CHANGED')
    return raw


def location(runtime, contract):
    runtime = Path(runtime)
    require(runtime.is_absolute() and '..' not in runtime.parts, 'INVALID_RUNTIME_PATH')
    for part in (*reversed(runtime.parents), runtime):plain(part, directory=True)
    return runtime / contract_spec(contract)[3]


def evidence_allowlist(path):
    value = guard.strict_json(read_plain(path, 65536))
    require(type(value) is dict and 1 <= len(value) <= 64, 'INVALID_REPLAY_EVIDENCE_ALLOWLIST')
    require(all(type(k) is str and re.fullmatch(r'[a-f0-9]{64}', k)
                and type(v) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}', v)
                for k, v in value.items()), 'INVALID_REPLAY_EVIDENCE_ALLOWLIST')
    return value


def _corpus(raw, profile, allowed, allow_synthetic):
    require(type(allow_synthetic) is bool, 'INVALID_REPLAY_POLICY')
    # Import lazily: a plan never requires a running transport or a corpus.
    module = importlib.import_module('chronos_transport.fixture_replay')
    return module.FixtureCorpus.from_bytes(raw, expected_sha256=profile.replay_corpus_sha256,
        fixture_sha256=profile.replay_fixture_sha256, allowed_evidence=allowed, allow_synthetic=allow_synthetic)


def state(ident, *, runtime=RUNTIME, contract='e1', allow_synthetic=False):
    identity(ident)
    area = location(runtime, contract)
    plain(area, directory=True)
    require({p.name for p in area.parent.iterdir()} == {area.name}, 'DEDICATED_REPLAY_RUNTIME_REQUIRED')
    names = {p.name for p in area.iterdir()}
    required = {'profile.json', 'corpus.json', 'evidence-allowlist.json', 'allowance.sqlite'}
    require(required <= names <= required | {'allowance.sqlite-wal', 'allowance.sqlite-shm'}, 'INVALID_REPLAY_STATE_FILES')
    for child in area.iterdir():plain(child)
    profile = Profile.parse(read_plain(area / 'profile.json', 4096))
    expected = plan(ident, profile.request_limit, profile.replay_corpus_sha256, profile.replay_fixture_sha256, contract=contract)
    require(profile.public() == expected, 'REPLAY_PROFILE_MISMATCH')
    allowed = evidence_allowlist(area / 'evidence-allowlist.json')
    corpus = _corpus(read_plain(area / 'corpus.json', MAX_CORPUS), profile, allowed, allow_synthetic)
    allowance = Allowance(area / 'allowance.sqlite', profile)
    return profile, allowance, corpus


def status(ident, *, runtime=RUNTIME, contract='e1', allow_synthetic=False):
    profile, allowance, _ = state(ident, runtime=runtime, contract=contract, allow_synthetic=allow_synthetic)
    return dict(schema_version='chronos.fixture-provider.v1', status='CONFIGURED_NOT_PROBED', mode=MODE,
                ready=False, model_tested=False, fresh_inference=False,
                profile=profile.public(), profile_sha256=profile.digest, binding_sha256=profile.digest,
                allowance=allowance.snapshot(),
                native_configuration=dict(baseURL='http://127.0.0.1:'+str(contract_spec(contract)[4])+'/v1/',
                    model=MODEL, profileSha256=profile.digest, reasoningEffort='none', contract=profile.response_contract,
                    executionMode=MODE, replayCorpusSha256=profile.replay_corpus_sha256,
                    replayFixtureSha256=profile.replay_fixture_sha256))


def prepare(ident, limit, corpus_sha256, fixture_sha256, *, corpus_path, allowed_evidence,
            authorize_id=None, runtime=RUNTIME, contract='e1', allow_synthetic=False):
    require(authorize_id == ident, 'EXPLICIT_INITIALIZATION_REQUIRED')
    profile = Profile.parse(canonical(plan(ident, limit, corpus_sha256, fixture_sha256, contract=contract)))
    raw = read_plain(corpus_path, MAX_CORPUS)
    # Full validation BEFORE creating any quota or directory. Trust is an
    # independently reviewed explicit allowlist, never extracted from the corpus.
    _corpus(raw, profile, allowed_evidence, allow_synthetic)
    area = location(runtime, contract)
    require(not area.exists(), 'PROVIDER_STATE_EXISTS_NO_RESET')
    require(not any(area.parent.iterdir()), 'REPLAY_RUNTIME_NOT_EMPTY')
    try:area.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:raise ProviderError('PROVIDER_STATE_EXISTS_NO_RESET') from None
    # Subsequent failure deliberately preserves the fenced partial attempt.
    for name, contents in (('profile.json', canonical(profile.public())), ('corpus.json', raw),
                           ('evidence-allowlist.json', canonical(allowed_evidence))):
        with (area / name).open('xb') as stream:
            stream.write(contents);stream.flush();os.fsync(stream.fileno())
    _corpus(read_plain(area / 'corpus.json', MAX_CORPUS), profile,
            evidence_allowlist(area / 'evidence-allowlist.json'), allow_synthetic)
    Allowance.create(area / 'allowance.sqlite', profile)
    return status(ident, runtime=runtime, contract=contract, allow_synthetic=allow_synthetic)


def configured(ident, *, runtime=RUNTIME, contract='e1', allow_synthetic=False):
    profile, allowance, corpus = state(ident, runtime=runtime, contract=contract, allow_synthetic=allow_synthetic)
    def handler(response_contract, input_json, prompt_sha256):
        require(response_contract == profile.response_contract, 'REPLAY_CONTRACT_CHANGED')
        result = corpus.lookup(response_contract, input_json, prompt_sha256)
        metadata = result.metadata
        require(type(metadata) is dict and metadata.get('mode') == MODE
                and metadata.get('fresh_inference') is False
                and metadata.get('corpus_sha256') == profile.replay_corpus_sha256
                and metadata.get('fixture_sha256') == profile.replay_fixture_sha256, 'REPLAY_RESPONSE_BINDING_CHANGED')
        return result
    return guard.configured_settings(schema(contract), allowance, recorded_handler=handler)


def serve(ident, *, runtime=RUNTIME, contract='e1', port=None):
    settings = configured(ident, runtime=runtime, contract=contract)
    port = guard.listener_port(contract, requested=port)
    server = guard.make_server(settings, port=port)
    def stop(*_):Thread(target=server.shutdown, daemon=True).start()
    for sig in (signal.SIGINT, signal.SIGTERM):signal.signal(sig, stop)
    print(json.dumps(dict(status='RECORDED_FIXTURE_TRANSPORT_LISTENING', mode=MODE,
                          profile_sha256=settings.profile_sha256, fresh_inference=False)), flush=True)
    try:server.serve_forever()
    finally:server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('plan', 'prepare', 'status', 'serve'):
        command = commands.add_parser(action)
        command.add_argument('--deployment-id', required=True)
        command.add_argument('--contract', choices=tuple(CONTRACTS), default='e1')
        if action in ('plan', 'prepare'):
            command.add_argument('--request-limit', required=True, type=int)
            command.add_argument('--corpus-sha256', required=True)
            command.add_argument('--fixture-sha256', required=True)
        if action == 'prepare':
            command.add_argument('--authorize-id', required=True)
            command.add_argument('--corpus', required=True)
            command.add_argument('--evidence-allowlist', required=True)
        if action in ('prepare', 'status', 'serve'):
            command.add_argument('--runtime', type=Path, default=None)
        if action == 'serve':command.add_argument('--port', type=int)
    args = parser.parse_args(argv)
    try:
        if args.action == 'plan':result = plan(args.deployment_id, args.request_limit, args.corpus_sha256, args.fixture_sha256, contract=args.contract)
        else:
            runtime = args.runtime or (Path('/opt/chronos/conversation-runtime') if args.contract=='c2-v2' else RUNTIME)
            if args.action == 'status':result = status(args.deployment_id, runtime=runtime, contract=args.contract)
            elif args.action == 'prepare':
                result = prepare(args.deployment_id, args.request_limit, args.corpus_sha256, args.fixture_sha256,
                    corpus_path=Path(args.corpus), allowed_evidence=evidence_allowlist(Path(args.evidence_allowlist)),
                    authorize_id=args.authorize_id, runtime=runtime, contract=args.contract)
            else:serve(args.deployment_id, runtime=runtime, contract=args.contract, port=args.port);return 0
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, ImportError, guard.Rejected):
        print(json.dumps(dict(status='REPLAY_STATE_REJECTED_PRESERVED', mode=MODE, ready=False,
                              model_tested=False, fresh_inference=False, retry_initialization=False)))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':raise SystemExit(main())
