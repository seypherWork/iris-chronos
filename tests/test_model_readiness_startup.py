"""Portable CPU tests; set CHRONOS_MODEL_READINESS_UNDER_TEST for another copy."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import importlib.util, os, sys, tempfile, unittest

HERE = Path(__file__).resolve().parent

def load_readiness():
    override = os.environ.get('CHRONOS_MODEL_READINESS_UNDER_TEST')
    candidates = [Path(override)] if override else [HERE / 'model_readiness.py',
        HERE.parent / 'deployment' / 'model_readiness.py', HERE.parent.parent / 'deployment' / 'model_readiness.py']
    filename = next(path for path in candidates if path.is_file())
    # Isolate the transport/control unit from installed services and provider profiles.
    provider = ModuleType('local_provider'); provider.RUNTIME = Path('/unused-runtime')
    spec = importlib.util.spec_from_file_location('_readiness_startup_unit', filename)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'local_provider': provider}):
        spec.loader.exec_module(module)
    return module

class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds

class ModelStartup(unittest.TestCase):
    def setUp(self):
        self.module = load_readiness()
        self.clock = Clock()
        self.model = 'test-local:8k'; self.digest = 'a' * 64
        self.profile = SimpleNamespace(model=self.model, digest='b' * 64, reasoning_effort='none')
        self.tags = {'models': [{'name': self.model, 'model': self.model, 'digest': self.digest,
            'size': 1024, 'details': {'format': 'gguf'}}]}
        resident = dict(self.tags['models'][0], context_length=8192, size_vram=512,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        self.residency = {'models': [resident]}
        self.neutral = dict(model=self.model, done=True, done_reason='stop', eval_count=5,
            prompt_eval_count=600, message={'role': 'assistant', 'content': '{"ready":true}'})

    def run_fixture(self, exchange):
        module = self.module; records = {}
        with tempfile.TemporaryDirectory(prefix='chronos-readiness-cpu-') as temp:
            area = Path(temp) / 'readiness'
            identity = dict(version=1, deployment_id='c' * 32, attempt_id='d' * 32,
                profile_sha256=self.profile.digest, model_sha256='e' * 64,
                expected_model_digest=self.digest, expected_context_length=8192)
            with patch.object(module, 'binding', return_value=(self.profile, area, identity)), \
                 patch.object(module, 'checked_parent'), patch.object(module, 'sync_dir'), \
                 patch.object(module, 'exclusive', return_value=nullcontext()), \
                 patch.object(module, 'write_new', side_effect=lambda path, value: records.update({path.name: value})), \
                 patch.object(module, 'exchange', side_effect=exchange), \
                 patch.object(module.time, 'monotonic', side_effect=self.clock.monotonic), \
                 patch.object(module.time, 'sleep', side_effect=self.clock.sleep):
                result = module.run('c' * 32, self.profile.digest, 'd' * 32, self.digest,
                                    8192, authorize_id='c' * 32)
        self.assertEqual(set(records['result.json']), {'binding', 'status', 'code', 'observed_at', 'metrics'})
        return result

    def test_connection_refused_then_ready_retries_get_and_posts_once(self):
        calls = []
        def exchange(path, body, deadline):
            calls.append((path, body, deadline))
            if path == '/api/tags':
                if sum(row[0] == path for row in calls) < 3:
                    raise self.module.ReadinessError('TRANSPORT_UNCERTAIN')
                return self.tags
            if path == '/api/chat': return self.neutral
            if path == '/api/ps': return self.residency
            self.fail('UNEXPECTED_ENDPOINT')
        result = self.run_fixture(exchange)
        self.assertEqual(result['status'], 'NEUTRAL_INFERENCE_OBSERVED')
        self.assertTrue(result['performed_request'])
        self.assertEqual([row[0] for row in calls], ['/api/tags'] * 3 + ['/api/chat', '/api/ps'])
        self.assertTrue(all(body is None for path, body, deadline in calls if path != '/api/chat'))
        self.assertTrue(all(deadline == 30 for path, body, deadline in calls if path == '/api/tags'))
        self.assertEqual(self.clock.now, 1)

    def test_wrong_model_fails_immediately_and_post_is_never_retried(self):
        for failure in ('wrong-model', 'post-transport'):
            with self.subTest(failure=failure):
                calls = []
                def exchange(path, body, deadline):
                    calls.append(path)
                    if path == '/api/tags':
                        return {'models': []} if failure == 'wrong-model' else self.tags
                    if path == '/api/chat':
                        raise self.module.ReadinessError('TRANSPORT_UNCERTAIN')
                    self.fail('NO_POST_RETRY_OR_RESIDENCY_AFTER_ERROR')
                result = self.run_fixture(exchange)
                self.assertEqual(result['status'], 'READINESS_UNVERIFIED')
                if failure == 'wrong-model':
                    self.assertEqual(result['code'], 'MODEL_IDENTITY_MISMATCH')
                    self.assertFalse(result['performed_request']); self.assertEqual(calls, ['/api/tags'])
                else:
                    self.assertEqual(result['code'], 'TRANSPORT_UNCERTAIN')
                    self.assertTrue(result['performed_request']); self.assertEqual(calls, ['/api/tags', '/api/chat'])
                self.assertEqual(self.clock.now, 0)

    def test_startup_timeout_sends_no_neutral_and_respects_outer_deadline(self):
        for overall, expected in ((240, 30), (2, 2)):
            with self.subTest(overall=overall):
                self.clock = Clock(); calls = []; self.module.DEADLINE_SECONDS = overall
                def exchange(path, body, deadline):
                    calls.append((path, body, deadline))
                    raise self.module.ReadinessError('TRANSPORT_UNCERTAIN')
                result = self.run_fixture(exchange)
                self.assertEqual(result['code'], 'DEADLINE_EXCEEDED')
                self.assertFalse(result['performed_request'])
                self.assertEqual(self.clock.now, expected)
                self.assertTrue(calls)
                self.assertTrue(all(path == '/api/tags' and body is None and deadline == expected
                                    for path, body, deadline in calls))

if __name__ == '__main__':
    unittest.main(verbosity=2)
