"""Portable CPU checks for prompt line endings in the actual native loaders.

No IRIS, model, replay corpus or workstation snapshot is required. The optional
CHRONOS_TEST_SOURCE_ROOT override only supports running this test before it is
copied into the repository's tests directory.
"""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest
from uuid import uuid4

SOURCE = Path(os.environ.get('CHRONOS_TEST_SOURCE_ROOT', Path(__file__).resolve().parents[1])).resolve()
_spec = importlib.util.spec_from_file_location(
    'chronos_prompt_normalization_loader_helpers', SOURCE/'tests/test_native_review_loader.py')
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
native_python = _helpers.native_python
PROMPTS = ('AGENT_INSTRUCTIONS.txt', 'EXTRACTION_INSTRUCTIONS.txt')


class NativePromptNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='chronos-prompt-')
        self.root = Path(self.temporary.name).resolve()
        self.aliases = set()
        self.runtime = native_python('Runtime', 'Module', 'root,namespace')
        self.agent = native_python('Agent', 'Load', 'root,namespace,simulation')
        # Keep fixture text independent of the checkout's own line-ending mix.
        # Only these two files are replaced inside our owned temporary copies.
        self.originals = {
            'AGENT_INSTRUCTIONS.txt': 'Propose an action from the supplied facts.\nDo not authorize dispatch.\n',
            'EXTRACTION_INSTRUCTIONS.txt': "Extract the customer's preference.\nReturn only the declared contract.\n",
        }

    def tearDown(self):
        # Remove only the private aliases created for this test's owned roots.
        # Shared loader locks and every other namespace's modules stay intact.
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix+'.') for prefix in self.aliases):
                del sys.modules[name]
        self.temporary.cleanup()

    def copy_packages(self, label, newline):
        root = self.root/label
        root.mkdir()
        for name in ('chronos_simulation', 'chronos_agent'):
            target = root/name
            target.mkdir()
            for source in (SOURCE/'src'/name).iterdir():
                if source.name == '__pycache__':
                    continue
                self.assertTrue(source.is_file() and not source.is_symlink())
                raw = source.read_bytes()
                if source.name in PROMPTS:
                    raw = self.originals[source.name].replace('\n', newline).encode('utf-8')
                (target/source.name).write_bytes(raw)
        return root

    def load(self, root, namespace):
        simulation = self.runtime(str(root), namespace)
        self.aliases.add(simulation.rsplit('.', 1)[0])
        agent = self.agent(str(root), namespace, simulation)
        prefix = agent.rsplit('.', 1)[0]
        self.aliases.add(prefix)
        return agent, sys.modules[prefix]

    def assert_prompts(self, package):
        self.assertEqual(package._chronos_prompt, self.originals['AGENT_INSTRUCTIONS.txt'])
        self.assertEqual(package._chronos_extraction_prompt, self.originals['EXTRACTION_INSTRUCTIONS.txt'])

    def test_lf_and_crlf_have_equal_prompts_but_distinct_raw_manifests(self):
        lf = self.copy_packages('lf', '\n')
        crlf = self.copy_packages('crlf', '\r\n')
        lf_namespace = 'CPU_PROMPT_LF_'+uuid4().hex
        crlf_namespace = 'CPU_PROMPT_CRLF_'+uuid4().hex
        lf_alias, lf_package = self.load(lf, lf_namespace)
        crlf_alias, crlf_package = self.load(crlf, crlf_namespace)
        self.assert_prompts(lf_package)
        self.assert_prompts(crlf_package)
        # Hashes remain sensitive to the actual installed source bytes.
        self.assertNotEqual(lf_package._chronos_binding[-1], crlf_package._chronos_binding[-1])
        self.assertNotEqual(lf_alias, crlf_alias)
        # Repeat the real cache branch: it must preserve normalized strings.
        again_alias, again = self.load(crlf, crlf_namespace)
        self.assertEqual(again_alias, crlf_alias)
        self.assertIs(again, crlf_package)
        self.assert_prompts(again)

    def test_actual_instruction_change_creates_a_new_binding_without_rewriting_the_old_one(self):
        root = self.copy_packages('changed', '\n')
        namespace = 'CPU_PROMPT_CHANGED_'+uuid4().hex
        old_alias, old = self.load(root, namespace)
        changed = self.originals['EXTRACTION_INSTRUCTIONS.txt']+'\nUse the newly declared business policy.\n'
        (root/'chronos_agent/EXTRACTION_INSTRUCTIONS.txt').write_bytes(changed.encode('utf-8'))
        new_alias, new = self.load(root, namespace)
        self.assertNotEqual(new_alias, old_alias)
        self.assertNotEqual(new._chronos_binding[-1], old._chronos_binding[-1])
        self.assertEqual(new._chronos_extraction_prompt, changed)
        self.assertEqual(old._chronos_extraction_prompt, self.originals['EXTRACTION_INSTRUCTIONS.txt'])
        self.assertEqual(new._chronos_prompt, old._chronos_prompt)

    def test_normalization_does_not_strip_unpaired_carriage_returns(self):
        root = self.copy_packages('unpaired', '\r\n')
        changed = self.originals['EXTRACTION_INSTRUCTIONS.txt']+'\rPreserve this distinct instruction separator.'
        (root/'chronos_agent/EXTRACTION_INSTRUCTIONS.txt').write_bytes(changed.replace('\n', '\r\n').encode('utf-8'))
        _, package = self.load(root, 'CPU_PROMPT_UNPAIRED_'+uuid4().hex)
        self.assertEqual(package._chronos_extraction_prompt, changed)
        self.assertIn('\r', package._chronos_extraction_prompt)
        self.assertNotEqual(package._chronos_extraction_prompt, self.originals['EXTRACTION_INSTRUCTIONS.txt'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
