"""Focused CPU contracts; no IRIS, Docker, accounts, model or real subprocess."""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util, json, os, re, subprocess, tempfile, unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location('test_'+name,ROOT/'deployment'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
cli=load('native_workflow');xml=load('workflow_callbacks')

def implementation(name):
    text=(ROOT/'deployment/NativeInstall.cls').read_text(encoding='utf-8')
    found=re.search(r'ClassMethod '+name+r'\([^\n]*\n\{\n(.*?)\n\}',text,re.S)
    if found is None:raise AssertionError('Missing method '+name)
    return found[1]

def scope():
    ident='a'*32;prefix='Chronos_'+ident[:12]
    def row(n,c,p):return dict(name=n,class_name=c,pool_size=p,enabled=True,foreground=False,
        settings=[dict(target='Host',name='AutoCreateRole',value='0')] if n=='Chronos.Clarifiers' else [])
    return dict(schema='chronos.workflow-optin-apply-scope.v1',deployment_id=ident,namespace='CHRONOS_'+ident[:12].upper(),
        operator=prefix+'_Operator',reader=prefix+'_Reader',origin='http://127.0.0.1:53198',application='/csp/chronos/',
        base_bundle_manifest_sha256='b'*64,source_sha256={n:'c'*64 for n in cli.PINS},workflow_globals=cli.GLOBALS,
        expected_before_items=[row(n,n,p) for n,p in cli.BASE],
        expected_after_items=[row(n,n,p) for n,p in cli.BASE]+[row(*v) for v in cli.EXTRA],
        workflow_records=dict(role='Chronos.Clarifiers',user=prefix+'_Operator',membership_id='Chronos.Clarifiers||'+prefix+'_Operator',ranking=3,title=''),
        required_build='2026.3.0AI.154.0',production='Chronos.App.Production',security_accounts_to_create=[],security_roles_to_create=[],security_grants_to_add=[])

def export(stamp='67888,6372.031635578',extra='',attribute='',implementation='Quit $$$OK',item='one'):
    return ('<?xml version="1.0" encoding="UTF-8"?><Export><Class name="Chronos.App.Production"'+attribute+'>'+
        '<TimeChanged>'+stamp+'</TimeChanged><Method name="OnStart"><Implementation>'+implementation+'</Implementation></Method>'+
        '<Method name="OnStop"><Implementation>Quit $$$OK</Implementation></Method>'+extra+
        '<XData name="ProductionDefinition"><Data><Production Name="Chronos.App.Production"><Item Name="'+item+'"/></Production></Data></XData>'+
        '</Class></Export>').encode()

class WorkflowDeliveryTests(unittest.TestCase):
    def policy(self,marker=None,sources=None,metadata=None):
        names=('Chronos.Deployment.NativeWorkflowInspect','Chronos.Deployment.NativeWorkflowApply')
        sources=sources or {n:'a'*64 for n in names};metadata=metadata or {n:'67888,6372.031635578' for n in names}
        marker=marker or dict(schema='chronos.workflow-delivery.v1',state='OWNED_READY',deploymentId='b'*32,
            baseBundleManifestSha256='c'*64,classes={n:dict(sourceSha256=sources[n],timeChanged=metadata[n]) for n in names})
        namespace={};exec('def call(id,bundle,markerJSON,sourcesJSON,metadataJSON):\n'+implementation('WorkflowDeliveryPolicy'),namespace)
        return namespace['call']('b'*32,'c'*64,json.dumps(marker),json.dumps(sources),json.dumps(metadata)),marker,sources,metadata

    def test_owned_marker_uses_exact_raw_metadata_strings(self):
        valid,marker,sources,metadata=self.policy();self.assertTrue(valid)
        name=next(iter(metadata));changed=dict(metadata);changed[name]='67888,6372.031635579'
        self.assertFalse(self.policy(marker,sources,changed)[0])
        for value in (678886372.031635578,True,''):
            changed=dict(metadata);changed[name]=value;self.assertFalse(self.policy(marker,sources,changed)[0])
        changed=dict(sources);changed[name]='d'*64;self.assertFalse(self.policy(marker,changed,metadata)[0])

    def test_missing_partial_foreign_and_extra_markers_cannot_be_reused(self):
        _,marker,sources,metadata=self.policy()
        for key,value in (('state','INSTALLING'),('state','PARTIAL_PRESERVED_NO_RETRY'),('deploymentId','d'*32),('baseBundleManifestSha256','d'*64)):
            changed=deepcopy(marker);changed[key]=value;self.assertFalse(self.policy(changed,sources,metadata)[0])
        changed=deepcopy(marker);changed['classes']['unexpected']={}
        self.assertFalse(self.policy(changed,sources,metadata)[0])

    def test_inspection_cannot_compile_and_fresh_apply_checks_both_class_catalogues_first(self):
        self.assertNotIn('$System.OBJ.Load(',implementation('Inspect'))
        self.assertNotIn('$System.OBJ.Load(',implementation('WorkflowDeliveryStatus'))
        absent=implementation('WorkflowDeliveryAbsent')
        self.assertIn('%Dictionary.ClassDefinition',absent);self.assertIn('%Dictionary.CompiledClass',absent)
        install=implementation('Install')
        self.assertLess(install.index('..Inspect('),install.index('Set ^ChronosInstall(id,"state")="INSTALLING"'))
        self.assertLess(install.index('..InstallWorkflowDelivery('),install.index('"RESOURCES"'))
        self.assertIn('Return definition.TimeChanged',implementation('WorkflowDeliveryTime'))

    def test_console_blocks_are_one_physical_line_with_separate_marker_and_halt(self):
        value=scope();digest=sha256(cli.canonical(value)).hexdigest();nonce='d'*32
        for action in ('inspect','apply','status','readback','export'):
            path=cli.proof_directory(value)/'before.xml' if action=='export' else None
            program=cli.program(action,value,digest,nonce,path)
            lines=program.splitlines();self.assertEqual(len(lines),3)
            self.assertIn('try {',lines[0]);self.assertIn('catch ex {',lines[0])
            self.assertTrue(lines[1].startswith('write !,"CHRONOS_NATIVE_INSTALL:'+nonce+':"'))
            self.assertEqual(lines[2],'halt');self.assertNotIn('$System.OBJ.Load(',program)
        bad=deepcopy(value);bad['namespace']='X" Kill ^bad'
        with self.assertRaises(ValueError):cli.program('apply',bad,digest,nonce)

    def test_authorization_and_environment_do_not_inherit_a_previous_apply(self):
        value=scope();digest=sha256(cli.canonical(value)).hexdigest();calls=[]
        def run(args,**kwargs):
            calls.append(kwargs);return SimpleNamespace(returncode=0,stderr='',stdout='fixed test result')
        base=SimpleNamespace(parse_output=lambda *_:dict(status='CPU_SIMULATED_RECEIPT',ready=False))
        with patch.dict(os.environ,{'CHRONOS_WORKFLOW_OPTIN_APPROVED':'old-token'}):
            cli.native('inspect',value,digest,run=run,base=base)
            self.assertNotIn('CHRONOS_WORKFLOW_OPTIN_APPROVED',calls[-1]['env'])
            with self.assertRaises(ValueError):cli.native('apply',value,digest,run=run,base=base)
            self.assertEqual(len(calls),1)
            cli.native('apply',value,digest,authorize_id=value['deployment_id'],run=run,base=base)
            self.assertEqual(calls[-1]['env']['CHRONOS_WORKFLOW_OPTIN_APPROVED'],value['deployment_id']+':'+digest)

    def test_timeout_is_uncertain_and_does_not_retry(self):
        value=scope();digest=sha256(cli.canonical(value)).hexdigest();calls=[]
        def run(*args,**kwargs):calls.append(1);raise subprocess.TimeoutExpired('iris',180)
        result=cli.native('apply',value,digest,authorize_id=value['deployment_id'],run=run)
        self.assertEqual(result['status'],'WORKFLOW_OUTCOME_UNCERTAIN_NO_RETRY');self.assertEqual(calls,[1])

    def test_callbacks_allow_only_exact_callbacks_and_direct_timechanged_metadata(self):
        self.assertTrue(xml.compare(export(),export(stamp='67888,6373.1',item='two'))['passed'])
        for changed in (export(extra='<Description>unexpected</Description>'),export(attribute=' extra="1"'),
                        export(implementation='Quit 0'),export(stamp='67888,86400.1'),export(stamp='not-a-stamp')):
            self.assertFalse(xml.compare(export(),changed)['passed'])

    def test_callbacks_reject_utf16_doctype_nul_and_invalid_utf8(self):
        evil='<!DOCTYPE Export [<!ENTITY x "expanded">]><Export><Class name="Chronos.App.Production">&x;</Class></Export>'
        for raw in (evil.encode('utf-16'),evil.encode('utf-8'),b'\xff',export()+b'\x00'):
            self.assertFalse(xml.compare(export(),raw)['passed'])

    def test_lost_apply_outcome_preserves_intent_and_no_second_mutation(self):
        value=scope();digest=sha256(cli.canonical(value)).hexdigest();calls=[]
        with tempfile.TemporaryDirectory(prefix='chronos-delivery-') as area:
            proof=Path(area)/'proof'
            def call(action,*_args,**kwargs):
                calls.append(action)
                if action=='inspect':return dict(status='OPTIN_PREFLIGHT_CLEAR',ready=False)
                if action=='export':kwargs['path'].write_bytes(export());return dict(status='CALLBACK_EXPORTED',ready=False)
                return dict(status='WORKFLOW_OUTCOME_UNCERTAIN_NO_RETRY',ready=False)
            with patch.object(cli,'proof_directory',return_value=proof):
                with self.assertRaises(ValueError):cli.flow('apply',value,digest,authorize_id=value['deployment_id'],call=call)
                self.assertTrue((proof/'intent.json').is_file());self.assertTrue((proof/'apply-result.json').is_file())
                with self.assertRaises(FileExistsError):cli.flow('apply',value,digest,authorize_id=value['deployment_id'],call=call)
            self.assertEqual(calls.count('apply'),1)

if __name__=='__main__':unittest.main()
