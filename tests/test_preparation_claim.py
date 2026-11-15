"""CPU checks of the actual pure claim method, plus explicit static COS checks.

These do not execute IRIS, accounts, model calls or native locks. Native compile,
Task/boot ordering and real cleanup-failure injection remain root acceptance work.
"""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import json, re, textwrap, unittest

HERE = Path(__file__).resolve().parent
SOURCE = (HERE.parent/'src/Chronos/Approval/Controller.cls').read_text(encoding='utf-8')

def body(name):
    value = re.search(r'^(?:Class)?Method ' + name + r'\([^\n]+\n\{\n(.*?)^\}', SOURCE, re.M | re.S)
    if not value: raise AssertionError('METHOD_NOT_FOUND:' + name)
    return value.group(1)

def load_claim_checker():
    namespace = {}
    code = 'def check(claimJSON,currentJSON):\n' + textwrap.indent(textwrap.dedent(body('PreparationClaimMatches')), '    ')
    exec(compile(code, 'actual-Controller.PreparationClaimMatches', 'exec'), namespace)
    return namespace['check']

CHECK = load_claim_checker()

def packet():
    return dict(ownerJob=1234, namespace='CHRONOS_TEST', ownerNonce='ABCDEF12-1234-5678-9ABC-1234567890AB',
        actor='principal-'+'1'*64, sessionBinding='session-'+'2'*64, decisionId='new-decision',
        decisionDigest='3'*64, anchorDigest='4'*64, generation='generation-1', snapshotId=17,
        authorityDigest='5'*64, previewId='prep-ABCDEF', requestId='request-1')

def encode(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))

class TwoPhaseContracts(unittest.TestCase):
    def test_real_private_checker_accepts_exact_unchanged_bindings(self):
        claim = packet(); original = deepcopy(claim)
        self.assertTrue(CHECK(encode(claim), encode(deepcopy(claim))))
        self.assertEqual(claim, original)

    def test_every_claim_binding_tamper_is_rejected(self):
        claim = packet()
        for key in claim:
            with self.subTest(field=key):
                current = deepcopy(claim)
                current[key] = current[key] + 1 if type(current[key]) is int else current[key] + 'x'
                self.assertFalse(CHECK(encode(claim), encode(current)))
        second_controller = dict(claim, ownerNonce='ABCDEF12-1234-5678-9ABC-1234567890AC')
        self.assertFalse(CHECK(encode(claim), encode(second_controller)))

    def test_malformed_duplicate_and_boolean_integer_claims_fail_closed(self):
        valid = packet()
        variants = [dict(valid, ownerJob=True), dict(valid, snapshotId=True), dict(valid, snapshotId=0),
            dict(valid, actor='admin'), dict(valid, sessionBinding='cookie'), dict(valid, extra='untrusted')]
        for invalid in variants:
            self.assertFalse(CHECK(encode(invalid), encode(invalid)))
        self.assertFalse(CHECK(encode(valid)[:-1] + ',"ownerJob":1234}', encode(valid)))
        self.assertFalse(CHECK('{"ownerJob":NaN}', encode(valid)))
        self.assertFalse(CHECK(None, encode(valid)))


if __name__ == '__main__':
    unittest.main()
