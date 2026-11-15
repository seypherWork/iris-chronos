"""Console-readiness failure injection; never starts IRIS or creates accounts."""
from contextlib import redirect_stdout
import importlib.util,io,json,os,subprocess,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('console_startup_under_test',SOURCE/'deployment/native_install.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Clock:
    def __init__(self):self.value=0
    def now(self):return self.value
    def sleep(self,seconds):self.value+=seconds

def ready():return types.SimpleNamespace(returncode=0,stdout='\n'+m.CONSOLE_MARKER+'IRIS for UNIX 2026.3.0AI (Build 154U)\n',stderr='')
def starting():return types.SimpleNamespace(returncode=239,stdout=m.STARTUP_REFUSAL+'\n',stderr='')

class ConsoleStartupTests(unittest.TestCase):
    def probe(self,responses,clock=None):
        clock=clock or Clock();calls=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            value=responses.pop(0)
            if isinstance(value,BaseException):raise value
            return value
        value=m.wait_console(run=run,monotonic=clock.now,sleep=clock.sleep)
        return value,calls

    def test_ready_is_readonly_and_has_real_newline_and_no_install_authorization(self):
        with patch.dict(os.environ,{'CHRONOS_INSTALL_APPROVED':'unrelated'}):
            result,calls=self.probe([ready()])
        self.assertEqual(result,dict(code='CONSOLE_READY',read_only=True,attempts=1))
        self.assertEqual(len(calls),1)
        args,kw=calls[0]
        self.assertEqual(args,['iris','session','IRIS','-U','%SYS'])
        self.assertEqual(kw['input'].count('\n'),1)
        self.assertTrue(kw['input'].endswith(' halt\n'))
        self.assertNotIn('Install(',kw['input']);self.assertNotIn('CHRONOS_INSTALL_APPROVED',kw['env'])

    def test_only_exact_startup_refusal_is_retried_before_success(self):
        result,calls=self.probe([starting(),starting(),ready()])
        self.assertEqual(result['attempts'],3);self.assertEqual(len(calls),3)
        self.assertTrue(all(row[1]['input'].startswith('write ')for row in calls))

    def test_other_exit_text_stderr_wrong_build_duplicate_and_error_are_not_retried(self):
        bad=[types.SimpleNamespace(returncode=1,stdout=m.STARTUP_REFUSAL,stderr=''),
             types.SimpleNamespace(returncode=239,stdout=m.STARTUP_REFUSAL+' altered',stderr=''),
             types.SimpleNamespace(returncode=239,stdout=m.STARTUP_REFUSAL,stderr='warning'),
             types.SimpleNamespace(returncode=0,stdout=ready().stdout.replace('154U','109U'),stderr=''),
             types.SimpleNamespace(returncode=0,stdout=ready().stdout*2,stderr=''),
             types.SimpleNamespace(returncode=0,stdout=ready().stdout+'ERROR #5001\n',stderr='')]
        for response in bad:
            with self.subTest(response=response):
                calls=[]
                def run(*a,**k):calls.append(1);return response
                c=Clock()
                with self.assertRaises(m.InstallError):m.wait_console(run=run,monotonic=c.now,sleep=c.sleep)
                self.assertEqual(calls,[1])

    def test_read_timeout_is_not_retried(self):
        calls=[]
        def run(*a,**k):calls.append(1);raise subprocess.TimeoutExpired('readonly',4)
        c=Clock()
        with self.assertRaisesRegex(m.InstallError,'READONLY_CONSOLE_TIMEOUT'):m.wait_console(run=run,monotonic=c.now,sleep=c.sleep)
        self.assertEqual(calls,[1])

    def test_deadline_is_absolute_and_is_never_renewed(self):
        c=Clock();calls=[]
        def run(*a,**k):calls.append(k['timeout']);return starting()
        with self.assertRaisesRegex(m.InstallError,'THIRTY_SECONDS'):m.wait_console(run=run,monotonic=c.now,sleep=c.sleep)
        self.assertEqual(c.value,30);self.assertEqual(len(calls),30)
        self.assertEqual(calls[-1],1)

    def test_success_arriving_after_deadline_is_rejected(self):
        c=Clock();calls=[]
        def run(*a,**k):calls.append(1);c.value=31;return ready()
        with self.assertRaisesRegex(m.InstallError,'THIRTY_SECONDS'):m.wait_console(run=run,monotonic=c.now,sleep=c.sleep)
        self.assertEqual(calls,[1])

    def invoke_main(self,console_error=None):
        events=[];health=types.ModuleType('native_health')
        def engine():events.append('engine');return {'ready':True}
        health.engine=engine
        def verify(*a,**k):events.append('verify')
        def console():
            events.append('console')
            if console_error:raise m.InstallError(console_error)
            return dict(code='CONSOLE_READY')
        def execute(*a,**k):events.append('execute');return dict(status='NATIVE_INSTALLED_DISABLED',ready=False)
        args=['apply','--deployment-id','a'*32,'--origin','http://127.0.0.1:53147','--application','/csp/chronos/','--manifest-sha256','b'*64,'--authorize-id','a'*32]
        with patch.object(m.os,'name','posix'),patch.object(m,'verify_source',verify),patch.object(m,'wait_console',console),patch.object(m,'execute',execute),patch.dict(sys.modules,{'native_health':health}),redirect_stdout(io.StringIO()):
            rc=m.main(args)
        return rc,events

    def test_main_rejects_before_mutation_when_console_is_not_ready(self):
        rc,events=self.invoke_main('READONLY_CONSOLE_TIMEOUT')
        self.assertEqual(rc,1);self.assertEqual(events,['verify','engine','console'])

    def test_main_sends_one_mutation_only_after_all_read_checks(self):
        rc,events=self.invoke_main()
        self.assertEqual(rc,0);self.assertEqual(events,['verify','engine','console','execute'])

    def test_existing_mutation_timeout_still_requires_original_outcome_read_not_retry(self):
        calls=[]
        def run(*a,**k):calls.append(k['input']);raise subprocess.TimeoutExpired('install',180)
        result=m.execute('apply','a'*32,'http://127.0.0.1:53147','/csp/chronos/','b'*64,authorize_id='a'*32,run=run)
        self.assertEqual(len(calls),1);self.assertIn('.Install(',calls[0])
        self.assertEqual(result,dict(status='INSTALL_OUTCOME_UNCERTAIN_DO_NOT_RETRY',ready=False))

if __name__=='__main__':unittest.main()
