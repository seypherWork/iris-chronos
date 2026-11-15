"""Use isolated copied tools; no native process or Docker needed."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CODE=r"""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'deployment'))
import native_install as m
bundle=Path(sys.argv[2]);aliases={k:bundle/k for k in ('src','deployment','tools')}
if sys.argv[5]!='-':aliases['src']=Path(sys.argv[5])
try:
    m.verify_source(sys.argv[3],sys.argv[4],bundle=bundle,aliases=aliases)
except m.InstallError as exc:
    print(json.dumps({'blocked':str(exc),'native_executed':False}))
else:
    print(json.dumps({'verified':True,'native_executed':False}))
"""

class BundleBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='native75-',dir=ROOT/'tests')
        cls.work=Path(cls.temp.name)
        sys.path.insert(0,str(ROOT/'tools'))
        import application_bundle as bundle
        cls.ab=bundle
        cls.bundle=cls.work/'bundle'
        bundle.build(ROOT,cls.bundle,'/csp/chronos/')
        cls.digest=hashlib.sha256((cls.bundle/'bundle-manifest.json').read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def call(self, *, source=None,digest=None,application='/csp/chronos/',bundle=None):
        p=subprocess.run([sys.executable,'-I','-B','-c',CODE,str(ROOT),str(bundle or self.bundle),digest or self.digest,application,str(source) if source else '-'],capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        r=json.loads(p.stdout)
        self.assertIs(r['native_executed'],False)
        return r

    def test_copied_pristine_package_and_aliases_verify(self):
        self.assertTrue(self.call()['verified'])

    def test_root_readme_is_verified_and_tampering_is_rejected(self):
        self.assertIn("README.md",self.ab.catalogue())
        pristine=self.call()
        self.assertTrue(pristine['verified'])
        altered=self.work/'altered-root-readme';shutil.copytree(self.bundle,altered)
        with (altered/'README.md').open('ab') as f:f.write(b'\nchanged root documentation\n')
        self.assertEqual(self.call(bundle=altered)['blocked'],'BUNDLE_VERIFICATION_FAILED')

    def test_ipm_module_is_verified_and_tampering_is_rejected(self):
        self.assertIn("module.xml", self.ab.catalogue())
        self.assertTrue(self.call()['verified'])
        altered=self.work/'altered-root-module';shutil.copytree(self.bundle,altered)
        with (altered/'module.xml').open('ab') as f:f.write(b'\n<!-- altered IPM module -->\n')
        self.assertEqual(self.call(bundle=altered)['blocked'],'BUNDLE_VERIFICATION_FAILED')

    def test_unexpected_root_file_is_rejected_before_native_command(self):
        altered=self.work/'unexpected-root-file';shutil.copytree(self.bundle,altered)
        (altered/'unexpected.txt').write_bytes(b'not in the closed bundle catalogue\n')
        self.assertEqual(self.call(bundle=altered)['blocked'],'BUNDLE_VERIFICATION_FAILED')

    def test_additional_class_is_rejected_before_native_command(self):
        extra=self.work/'extra-class';shutil.copytree(self.bundle/'src',extra)
        (extra/'Chronos/Extra.cls').write_text('Class Chronos.Extra Extends %RegisteredObject {}\n')
        self.assertEqual(self.call(source=extra)['blocked'],'MOUNT_ALIAS_CONTENTS_CHANGED')

    def test_additional_python_is_rejected_before_native_command(self):
        extra=self.work/'extra-python';shutil.copytree(self.bundle/'src',extra)
        (extra/'chronos_simulation/old_helper.py').write_text('raise RuntimeError("must not execute")\n')
        self.assertEqual(self.call(source=extra)['blocked'],'MOUNT_ALIAS_CONTENTS_CHANGED')

    def test_modified_alias_bytes_are_rejected(self):
        extra=self.work/'changed';shutil.copytree(self.bundle/'src',extra)
        with (extra/'chronos_web/boot.mjs').open('ab') as f:f.write(b'\n// changed\n')
        self.assertEqual(self.call(source=extra)['blocked'],'MOUNT_ALIAS_DRIFT')

    def test_wrong_digest_and_api_route_are_rejected(self):
        self.assertEqual(self.call(digest='0'*64)['blocked'],'BUNDLE_VERIFICATION_FAILED')
        self.assertEqual(self.call(application='/csp/chronos-other/')['blocked'],'BUNDLE_APPLICATION_MISMATCH')

    def test_installer_class_declaration_is_not_exempted(self):
        with self.assertRaises(self.ab.web.StageError):
            self.ab.structure({'deployment/NativeInstall.cls':b'Class Chronos.Unlisted Extends %RegisteredObject\n{}\n'})

if __name__=='__main__':unittest.main()
