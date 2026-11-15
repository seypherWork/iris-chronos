"""File-only setup checks. Mocked provenance success is not a real capture or IRIS proof."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'src'))
sys.path.insert(0, str(SOURCE / 'tools'))
spec = importlib.util.spec_from_file_location('fixture_jury_setup_test', SOURCE / 'deployment/jury_setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
spec = importlib.util.spec_from_file_location('fixture_install_test_bank', SOURCE / 'tests/transport/test_fixture_replay.py')
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)


class FixtureInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chrinst-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'workspace'
        self.corpus = self.root / 'corpus.json'
        self.allowlist = self.root / 'allowlist.json'
        self.provider = setup.replay_module(SOURCE)
        self.ident = 'd' * 32
        self.image = 'sha256:' + 'e' * 64
        rows = [bank.record(bank.f.E1, bank.e1(name), bank.e1_answer(name), 'synthetic-' + name)
                for name, _, _ in bank.f.CASE_RULES]
        rows += [bank.record(bank.f.C2, bank.c2(question), bank.c2_answer(bank.c2(question)), 'synthetic-chat-' + str(i))
                 for i, question in enumerate(bank.f.QUESTIONS)]
        self.raw = bank.encoded(rows)
        self.corpus.write_bytes(self.raw)
        self.allowlist.write_text(json.dumps(bank.ALLOWLIST), encoding='utf-8')
        self.digest = sha256(self.raw).hexdigest()

    def prepare(self, **extra):
        return setup.prepare_recorded(str(self.target), self.image, 53141, str(self.corpus), self.digest,
                                      str(self.allowlist), deployment_id=self.ident, source=SOURCE, **extra)

    def mocked_corpus_validation(self):
        # Explicit seam: only file assembly is tested under this mock. The real
        # production entry point rejects these SYNTHETIC_TEST_ONLY records.
        return patch.object(self.provider, '_corpus', return_value=None)

    def mocked_prepare(self):
        with patch.object(setup, 'replay_module', return_value=self.provider), self.mocked_corpus_validation():
            return self.prepare()

    def mocked_verify(self):
        with patch.object(setup, 'replay_module', return_value=self.provider), self.mocked_corpus_validation():
            return setup.verify(str(self.target), source=SOURCE)

    def test_real_validator_rejects_synthetic_capture_before_any_output(self):
        with self.assertRaisesRegex(ValueError, 'REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE'):
            self.prepare()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.corpus.read_bytes(), self.raw)

    def test_wrong_expected_corpus_digest_rejects_before_output(self):
        with self.assertRaisesRegex(ValueError, 'RECORDED_CORPUS_BYTES_CHANGED'):
            setup.prepare_recorded(str(self.target), self.image, 53141, str(self.corpus), 'f' * 64,
                                   str(self.allowlist), deployment_id=self.ident, source=SOURCE)
        self.assertFalse(self.target.exists())

    def test_invalid_capture_allowlist_rejects_before_output(self):
        self.allowlist.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'INVALID_REPLAY_EVIDENCE_ALLOWLIST'):
            self.prepare()
        self.assertFalse(self.target.exists())

    def test_mocked_provenance_file_setup_needs_no_model_gpu_or_allowance(self):
        result = self.mocked_prepare()
        self.assertEqual(result, self.mocked_verify())
        self.assertEqual(result['mode'], 'RECORDED_FIXTURE_SETUP_ONLY')
        self.assertEqual(result['profiles'], ['recorded-fixture'])
        self.assertEqual(result['compose_files'], ['compose.yaml', 'compose.web-local.yaml', 'compose.replay.yaml'])
        self.assertFalse(result['installed'])
        self.assertFalse(result['allowances_initialized'])
        self.assertEqual((result['accounts_created'], result['services_started'], result['model_calls']), (0, 0, 0))
        self.assertEqual(result['environment']['CHRONOS_DEPLOYMENT_ID'], self.ident)
        self.assertFalse(any('GPU' in k or 'MODEL' in k or 'OLLAMA' in k for k in result['environment']))
        self.assertFalse((self.target / 'model-home').exists())
        self.assertEqual(list(self.target.rglob('*.sqlite')), [])
        self.assertEqual(list((self.target / 'stage/guard').iterdir()), [])
        self.assertEqual(list((self.target / 'chat-state').iterdir()), [])
        for name, version in [('e1', 3), ('c2', 6)]:
            profile = json.loads((self.target / ('profiles/' + name + '.json')).read_bytes())
            self.assertEqual(profile['version'], version)
            self.assertEqual(profile['provider'], 'recorded-fixture')
            self.assertEqual(profile['model'], 'chronos-recorded-fixture-v1')
            self.assertIsNone(profile['local_port'])
            self.assertEqual(profile['replay_corpus_sha256'], self.digest)

    def test_missing_case_or_question_rejects_before_output_even_with_mocked_provenance(self):
        body = json.loads(self.raw)
        body['records'].pop()
        self.raw = json.dumps(body).encode()
        self.digest = sha256(self.raw).hexdigest()
        self.corpus.write_bytes(self.raw)
        with patch.object(setup, 'replay_module', return_value=self.provider), self.mocked_corpus_validation():
            with self.assertRaisesRegex(ValueError, 'RECORDED_CORPUS_INCOMPLETE'):
                self.prepare()
        self.assertFalse(self.target.exists())

    def test_corpus_allowlist_and_profile_tampering_are_rejected(self):
        self.mocked_prepare()
        paths = [self.target / 'fixtures/corpus.json', self.target / 'fixtures/evidence-allowlist.json',
                 self.target / 'profiles/c2.json']
        for path in paths:
            original = path.read_bytes()
            if path.name == 'c2.json':
                altered = json.loads(original); altered['request_limit'] = 1000
                path.write_text(json.dumps(altered), encoding='utf-8')
            else:
                path.write_bytes(original + b' ')
            with self.subTest(path=path.name):
                with self.assertRaises(ValueError):
                    self.mocked_verify()
            path.write_bytes(original)

    def test_extra_compose_gpu_or_used_state_never_passes_pristine_verification(self):
        self.mocked_prepare()
        receipt_path = self.target / setup.RECEIPT
        original = json.loads(receipt_path.read_bytes())
        for field in ('environment', 'compose_files'):
            changed = deepcopy(original)
            if field == 'environment':
                changed[field]['CHRONOS_GPU_DEVICE_ID'] = 'all'
            else:
                changed[field].append('compose.local-gpu.yaml')
            receipt_path.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaises(ValueError):
                self.mocked_verify()
        receipt_path.write_text(json.dumps(original), encoding='utf-8')
        (self.target / 'chat-state/used.txt').write_text('preserve', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'WORKSPACE_ALREADY_USED'):
            self.mocked_verify()
        self.assertEqual((self.target / 'chat-state/used.txt').read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
