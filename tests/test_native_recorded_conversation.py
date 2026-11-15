"""C2 provider status checks: no IRIS, model request, account or network service."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_recorded_chat_test', SOURCE / 'deployment/native_conversation.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
IDENT = 'a' * 32
BUNDLE = 'b' * 64


def status_packet():
    profile = {'version': 6, 'deployment_id': IDENT, 'provider': 'recorded-fixture',
               'model': 'chronos-recorded-fixture-v1', 'schema_sha256': 'c' * 64,
               'request_limit': 24, 'local_port': None, 'reasoning_effort': 'none',
               'response_contract': native.CONTRACTS['c2-v2'],
               'replay_corpus_sha256': 'd' * 64, 'replay_fixture_sha256': 'e' * 64}
    digest = sha256(json.dumps(profile, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return {'schema_version': 'chronos.fixture-provider.v1', 'status': 'CONFIGURED_NOT_PROBED',
            'mode': 'RECORDED_FIXTURE', 'ready': False, 'model_tested': False, 'fresh_inference': False,
            'profile': profile, 'profile_sha256': digest, 'binding_sha256': digest,
            'allowance': {'profile_sha256': digest, 'used': 0, 'remaining': 24, 'outcomes': {}},
            'native_configuration': {'baseURL': 'http://127.0.0.1:11514/v1/', 'model': profile['model'],
                'profileSha256': digest, 'reasoningEffort': 'none', 'contract': native.CONTRACTS['c2-v2'],
                'executionMode': 'RECORDED_FIXTURE', 'replayCorpusSha256': 'd' * 64, 'replayFixtureSha256': 'e' * 64}}


class NativeRecordedConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chrnc-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'runtime'
        self.root.mkdir()
        self.runtime_patch = patch.object(native, 'CONVERSATION_RUNTIME', self.root)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.calls = []

    def command(self, packet=None, *, returncode=0, stderr=b'', raw=None):
        # Deliberately simulated process output for protocol-negative tests.
        def run(args, **options):
            self.calls.append((args, options))
            return SimpleNamespace(returncode=returncode, stderr=stderr,
                stdout=raw if raw is not None else json.dumps(packet).encode())
        return run

    def read(self, run):
        return native.provider_profile(IDENT, run=run)

    def flow(self, run, **extra):
        invoked = []
        def invoke(*args, **kwargs):
            invoked.append((args, kwargs))
            return {'status': 'MOCK_NATIVE_STATUS_ONLY'}
        options = dict(read=lambda ident: native.provider_profile(ident, run=run), invoke=invoke, contract='c2-v2')
        options.update(extra)
        return invoked, lambda: native.flow('status', IDENT, 'http://127.0.0.1:53145', '/csp/chronos/',
                                          BUNDLE, status_packet()['profile_sha256'], **options)

    def test_replay_status_is_a_fixed_bounded_subprocess_not_a_live_import(self):
        (self.root / 'fixture-conversation-provider').mkdir()
        packet = status_packet()
        with patch.object(native, 'sibling', side_effect=AssertionError('must not load live or replay module')):
            self.assertEqual(self.read(self.command(packet)), packet)
        args, options = self.calls[0]
        self.assertEqual(args, ['/usr/bin/python3', '-B', str(SOURCE / 'deployment/replay_provider.py'),
            'status', '--deployment-id', IDENT, '--contract', 'c2-v2', '--runtime', str(self.root)])
        self.assertEqual(options, {'capture_output': True, 'timeout': 10, 'check': False})

    def test_live_provider_uses_the_existing_status_unchanged(self):
        (self.root / 'conversation-provider').mkdir()
        expected = {'legacy_live_status': True}
        live_calls = []
        stub = SimpleNamespace(status=lambda ident: live_calls.append(ident) or expected)
        with patch.object(native, 'sibling', return_value=stub) as loaded:
            actual = self.read(lambda *_a, **_kw: self.fail('must not launch replay subprocess'))
        self.assertIs(actual, expected)
        self.assertEqual(live_calls, [IDENT])
        loaded.assert_called_once_with('conversation_provider')

    def test_empty_mixed_or_unexpected_runtime_rejects_before_native_invocation(self):
        for names in [[], ['conversation-provider', 'fixture-conversation-provider'], ['other-provider']]:
            created = []
            for name in names:
                path = self.root / name; path.mkdir(); created.append(path)
            invoked, action = self.flow(self.command(status_packet()))
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, 'EXACTLY_ONE_OWNED'):
                action()
            self.assertEqual(invoked, [])
            self.assertEqual(self.calls, [])
            for path in created:
                path.rmdir()

    def test_incompatible_or_malformed_recorded_status_never_invokes_native(self):
        (self.root / 'fixture-conversation-provider').mkdir()
        changes = [lambda p: p.update(mode='LIVE_MODEL'), lambda p: p.update(fresh_inference=True),
                   lambda p: p.update(model_tested=True), lambda p: p.update(ready=True),
                   lambda p: p['profile'].update(provider='ollama'), lambda p: p['profile'].update(version=4),
                   lambda p: p['profile'].update(deployment_id='f' * 32),
                   lambda p: p['profile'].update(replay_corpus_sha256='bad'),
                   lambda p: p.update(profile_sha256='f' * 64),
                   lambda p: p['allowance'].update(profile_sha256='f' * 64),
                   lambda p: p['native_configuration'].update(executionMode='LIVE_MODEL')]
        for mutate in changes:
            packet = status_packet(); mutate(packet)
            invoked, action = self.flow(self.command(packet))
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(invoked, [])

    def test_profile_argument_mismatch_rejects_before_invocation(self):
        (self.root / 'fixture-conversation-provider').mkdir()
        invoked = []
        with self.assertRaisesRegex(ValueError, 'C1_PROFILE_CHANGED'):
            native.flow('status', IDENT, 'http://127.0.0.1:53145', '/csp/chronos/', BUNDLE, 'f' * 64,
                        read=lambda ident: self.read(self.command(status_packet())),
                        invoke=lambda *_a, **_kw: invoked.append(True), contract='c2-v2')
        self.assertEqual(invoked, [])

    def test_status_transport_failures_and_duplicate_json_fields_are_rejected(self):
        (self.root / 'fixture-conversation-provider').mkdir()
        for run in [self.command(status_packet(), returncode=1), self.command(status_packet(), stderr=b'private error'),
                    self.command(raw=b'not json'), self.command(raw=b'x' * 16385),
                    self.command(raw=b'{"mode":"LIVE_MODEL","mode":"RECORDED_FIXTURE"}')]:
            with self.assertRaises(ValueError):
                self.read(run)
        for error in [OSError('private path'), subprocess.TimeoutExpired('private command', 10)]:
            with patch.object(native.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(ValueError, 'RECORDED_PROVIDER_UNAVAILABLE'):
                    self.read(lambda *_a, **_kw: (_ for _ in ()).throw(error))

    def test_profile_changes_after_mock_native_status_are_reported_without_retry(self):
        (self.root / 'fixture-conversation-provider').mkdir()
        count = 0
        def run(args, **options):
            nonlocal count
            count += 1
            packet = status_packet()
            if count == 2:
                packet['profile']['replay_fixture_sha256'] = 'f' * 64
            return self.command(packet)(args, **options)
        invoked, action = self.flow(run)
        self.assertEqual(action()['status'], 'C1_PROFILE_CHANGED_USE_STATUS')
        self.assertEqual(len(invoked), 1)
        self.assertEqual(count, 2)

    def test_real_fixture_status_subprocess_reads_only_local_state_without_inference(self):
        # This uses the genuine preserved capture corpus, but does NOT repeat
        # its historical model calls. Only a fresh local quota/status is read.
        replay = native.sibling('replay_provider')
        evidence = SOURCE / 'deployment/evidence/fixture-bank-154-20261113'
        raw = (evidence / 'corpus.json').read_bytes()
        digest = sha256(raw).hexdigest()
        summary = json.loads((evidence / 'summary.json').read_bytes())
        replay.prepare(IDENT, 24, digest, summary['fixture_sha256'], corpus_path=evidence / 'corpus.json',
                       allowed_evidence=replay.evidence_allowlist(evidence / 'evidence-allowlist.json'),
                       authorize_id=IDENT, runtime=self.root, contract='c2-v2')
        observed = []
        def actual_process(args, **options):
            self.assertEqual(args[:2], ['/usr/bin/python3', '-B'])
            observed.append(args)
            # Test-host adaptation only: production retains its fixed Linux executable.
            return subprocess.run([sys.executable, *args[1:]], **options)
        result = self.read(actual_process)
        self.assertEqual(len(observed), 1)
        self.assertEqual(result['profile']['provider'], 'recorded-fixture')
        self.assertEqual(result['allowance']['used'], 0)
        self.assertEqual(result['allowance']['remaining'], 24)
        self.assertFalse(result['fresh_inference'])
        self.assertFalse(result['model_tested'])
        self.assertFalse(result['ready'])


if __name__ == '__main__':
    unittest.main()
