"""Negative checks mutate in-memory copies, never the preserved evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('restart_verify', ROOT / 'verify.py')
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class RetainedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'summary.json').read_bytes())

    def test_retained_packet_passes(self):
        self.assertEqual(verify.verify_summary(self.data)['accepted_recovery_effects'], 1)

    def test_second_submit_is_rejected(self):
        self.data['destination_final']['rawCalls'].append(copy.deepcopy(self.data['destination_final']['rawCalls'][0]))
        with self.assertRaisesRegex(ValueError, 'one recorded Submit'):
            verify.verify_records(self.data)

    def test_receipt_replacement_is_rejected(self):
        self.data['recovered_operation']['lastReceiptId'] = 'a-different-receipt'
        with self.assertRaisesRegex(ValueError, 'receipt identity'):
            verify.verify_records(self.data)

    def test_new_attempt_is_rejected(self):
        self.data['recovered_operation']['attemptId'] = 'attempt-2'
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            verify.verify_records(self.data)

    def test_already_persisted_receipt_is_rejected(self):
        self.data['before_cut']['iris']['reference'] = 'already-saved'
        with self.assertRaisesRegex(ValueError, 'already reached'):
            verify.verify_records(self.data)

    def test_oom_is_rejected(self):
        self.data['cut']['OOMKilled'] = True
        with self.assertRaisesRegex(ValueError, 'intentional stop'):
            verify.verify_records(self.data)

    def test_second_effect_is_rejected(self):
        self.data['destination_final']['accepted']['submits'] = 2
        with self.assertRaisesRegex(ValueError, 'one accepted recovery'):
            verify.verify_records(self.data)

    def test_consistent_rewrite_is_rejected_by_packet_hash(self):
        old = self.data['recovered_operation']['operationId']
        self.data = json.loads(json.dumps(self.data).replace(old, 'consistently-rewritten-operation'))
        with self.assertRaisesRegex(ValueError, 'packet integrity'):
            verify.verify_summary(self.data)

    def test_late_stop_is_rejected(self):
        self.data['before_cut']['barrier']['start_utc'] -= 60
        with self.assertRaisesRegex(ValueError, 'outside the receipt barrier'):
            verify.verify_records(self.data)


if __name__ == '__main__':
    unittest.main()
