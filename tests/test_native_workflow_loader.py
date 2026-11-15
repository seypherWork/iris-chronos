"""Pure SYS-loader policy/file checks, not ObjectScript compilation or IRIS."""
from hashlib import sha256
from pathlib import Path
import json
import re
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'deployment/NativeInstall.cls'

def implementation(name):
    source=SOURCE.read_text(encoding='utf-8')
    match=re.search(r'ClassMethod '+name+r'\([^\n]*\n\{\n(.*?)\n\}',source,re.S)
    if match is None:raise AssertionError('Method not found: '+name)
    return match.group(1)

def python_method(name,args):
    scope={};exec('def call('+args+'):\n'+implementation(name),scope)
    return scope['call']

class WorkflowSystemQueryLoaderTests(unittest.TestCase):
    def setUp(self):
        self.policy=python_method('WorkflowQueryPolicy','sourceSHA,present,markerData,markerJSON,metadataReady')
        self.marker=dict(schema='chronos.workflow-system-query.v1',state='READY',sourceSha256='a'*64,
            deploymentId='b'*32,manifestSha256='c'*64)

    def status(self,*,source='a'*64,present=True,data=1,marker=None,meta=True):
        raw=json.dumps(self.marker if marker is None else marker)
        return json.loads(self.policy(source,present,data,raw,meta))

    def test_first_compile_requires_absent_class_and_absent_marker(self):
        self.assertEqual(self.status(present=False,data=0)['status'],'ABSENT_AND_SOURCE_VERIFIED')
        self.assertEqual(self.status(data=0)['status'],'QUERY_CLASS_UNOWNED')
        self.assertFalse(self.status(data=0)['reuse'])

    def test_owned_ready_reuses_without_a_new_compile(self):
        result=self.status()
        self.assertEqual(result['status'],'OWNED_READY_SOURCE_MATCHED')
        self.assertIs(result['reuse'],True)

    def test_missing_changed_or_malformed_source_fails_closed(self):
        for source in ('','A'*64,'not-a-digest'):
            self.assertEqual(self.status(source=source)['status'],'QUERY_SOURCE_UNAVAILABLE')
        self.assertEqual(self.status(source='d'*64)['status'],'QUERY_SOURCE_CHANGED')

    def test_partial_loading_and_repeated_failure_never_allow_retry(self):
        for state in ('LOADING','PARTIAL_PRESERVED_NO_RETRY'):
            marker={**self.marker,'state':state}
            for present in (False,True):
                for _ in range(2):
                    result=self.status(marker=marker,present=present)
                    self.assertEqual(result['status'],'QUERY_PARTIAL_NO_RETRY')
                    self.assertFalse(result['reuse'])

    def test_incomplete_unknown_and_subscripted_markers_do_not_allow_retry(self):
        for marker in ({},{**self.marker,'state':'UNKNOWN'},{**self.marker,'extra':True},
                       {k:v for k,v in self.marker.items() if k!='manifestSha256'}):
            self.assertEqual(self.status(marker=marker)['status'],'QUERY_MARKER_INVALID')
        for data in (10,11):
            self.assertEqual(self.status(data=data)['status'],'QUERY_MARKER_INVALID')

    def test_ready_requires_present_class_and_native_metadata(self):
        for present,meta in ((False,False),(False,True),(True,False)):
            self.assertEqual(self.status(present=present,meta=meta)['status'],'QUERY_METADATA_UNAVAILABLE')

    def test_duplicate_marker_fields_are_rejected(self):
        raw=json.dumps(self.marker)[:-1]+',"state":"READY"}'
        self.assertEqual(json.loads(self.policy('a'*64,True,1,raw,True))['status'],'QUERY_MARKER_INVALID')

    def test_file_hash_preserves_exact_utf8_bytes_and_line_endings(self):
        call=python_method('WorkflowQuerySourceSHA256','')
        for raw in ('Class X { // Café\r\n}\r\n'.encode(),'Class X { // Café\n}\n'.encode()):
            with tempfile.TemporaryDirectory(prefix='chronos-query-') as area:
                target=Path(area)/'query.cls';target.write_bytes(raw)
                with patch('pathlib.Path',return_value=target) as fixed:
                    self.assertEqual(call(),sha256(raw).hexdigest())
                    fixed.assert_called_once_with('/opt/chronos/deployment/WorkflowAccountQuery.cls')

    def test_empty_oversized_invalid_utf8_and_symlink_sources_are_rejected(self):
        call=python_method('WorkflowQuerySourceSHA256','')
        with tempfile.TemporaryDirectory(prefix='chronos-query-') as area:
            target=Path(area)/'query.cls'
            for raw in (b'',b'\xff',b'x'*1048577):
                target.write_bytes(raw)
                with patch('pathlib.Path',return_value=target):self.assertEqual(call(),'')
            with patch('pathlib.Path') as fixed:
                fixed.return_value.parents=()
                fixed.return_value.is_symlink.return_value=True
                self.assertEqual(call(),'')

    def test_inspection_boundaries_never_compile_or_write(self):
        for name in ('Inspect','WorkflowQueryStatus','WorkflowQueryMetadata','WorkflowQueryPolicy','WorkflowQuerySourceSHA256'):
            body=implementation(name)
            self.assertNotIn('$System.OBJ.Load(',body)
            self.assertNotRegex(body,r'Set\s+\^ChronosInstall')
        loader=implementation('InstallWorkflowQuery')
        self.assertEqual(loader.count('$System.OBJ.Load('),1)
        self.assertLess(loader.index('OWNED_READY_SOURCE_MATCHED'),loader.index('$System.OBJ.Load('))
        self.assertLess(loader.index('ABSENT_AND_SOURCE_VERIFIED'),loader.index('$System.OBJ.Load('))
        self.assertIn('PARTIAL_PRESERVED_NO_RETRY',loader)

    def test_loader_runs_before_resource_and_application_mutations(self):
        body=implementation('Install')
        self.assertLess(body.index('..InstallWorkflowQuery('),body.index('"RESOURCES"'))
        self.assertLess(body.index('..InstallWorkflowQuery('),body.index('..ApplicationPhase('))
        self.assertIn('result.workflowSystemQuery=..WorkflowQueryStatus()',implementation('Inspect'))
        self.assertNotIn('..Add(rows,"workflow',implementation('Inspect'))

    def test_compiled_parameter_uses_observed_dictionary_default_property(self):
        body=implementation('WorkflowQueryMetadata')
        # The retained build154 dictionary probe reads CompiledParameter.Default.
        self.assertIn('parameter.Default="%Admin_Secure"',body)
        self.assertNotIn('parameter.Value',body)

if __name__=='__main__':unittest.main()
