"""Fresh build154 Workflow opt-in; provisioned helpers only, no compilation here.

Run inside the owned container after native_install apply, before onboarding.
Adds five production items and three Workflow records for the existing Operator.
Never creates/enables Security accounts, roles, grants, routes or model calls.
"""
from pathlib import Path
from hashlib import sha256
import argparse, importlib.util, json, os, re, subprocess, sys, uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = (('Chronos.App.Input',0),('Chronos.App.Process',1),('Chronos.App.Worker',1),
        ('Chronos.Agent.Operation',1),('Chronos.Approval.Input',0),('Chronos.Approval.Operation',0))
EXTRA = (('Chronos.Workflow.Input','Chronos.Workflow.Input',0),('Chronos.Workflow.Process','Chronos.Workflow.Process',1),
         ('Chronos.Clarifiers','EnsLib.Workflow.Operation',1),('Chronos.Workflow.AccountService','Chronos.Workflow.AccountService',0),
         ('Chronos.Workflow.AccountOperation','Chronos.Workflow.AccountOperation',1))
PINS = ('deployment/NativeInstall.cls','deployment/WorkflowAccountQuery.cls','src/Chronos/App/Production.cls') + tuple(
    'src/Chronos/Workflow/'+n+'.cls' for n in ('Request','Store','Process','Controller','AccountState','ContextGate',
    'AccountOperation','AccountService','Decisions','Entry','Input','Policy','API'))
GLOBALS = sorted([stem+s for stem in ('EnsLib.W.RoleDefinition','EnsLib.W.UserDefinition','EnsLib.W.RoleMembership',
    'EnsLib.W.Worklist','Ens.MessageBody','Ens.Config.Production','Ens.Config.Item') for s in ('D','I','S')]+
    ['Ens.Conf.SettingS','ChronosRuntime','ChronosDecision16','ChronosAuthority14','ChronosWeb'])

def need(value, code):
    if not value: raise ValueError(code)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=True, allow_nan=False).encode()

def sibling(name):
    path=HERE/(name+'.py'); spec=importlib.util.spec_from_file_location('_workflow_'+name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def validate_scope(raw):
    need(type(raw) is bytes and 0<len(raw)<=32768,'INVALID_SCOPE_BYTES')
    text=(HERE/'NativeWorkflowInspect.cls').read_bytes().decode('utf-8')
    match=re.search(r'ClassMethod Validate\([^\n]*\n\{\n(.*?)\n\}',text.replace('\r\n','\n'),re.S)
    need(match is not None,'SCOPE_POLICY_MISSING')
    namespace={};exec('def check(raw):\n'+match[1],namespace)
    normalized=namespace['check'](raw.decode('utf-8'));need(normalized,'SCOPE_REJECTED')
    return json.loads(normalized),normalized.encode()

def make_scope(ident,origin,bundle,root=ROOT):
    source=(root/'src/Chronos/App/Production.cls').read_bytes().decode('utf-8')
    match=re.search(r'XData ProductionDefinition\s*\{\s*(<Production\b.*?</Production>)\s*\}',source,re.S)
    need(match is not None,'BASE_PRODUCTION_DEFINITION_MISSING')
    production=ET.fromstring(match[1]);items=production.findall('Item')
    need(production.get('Name')=='Chronos.App.Production' and len(items)==6,'BASE_PRODUCTION_CHANGED')
    for item,(name,pool) in zip(items,BASE):
        need(item.attrib==dict(Name=name,ClassName=name,PoolSize=str(pool),Enabled='true',Foreground='false') and not list(item),'BASE_PRODUCTION_ITEM_CHANGED')
    prefix='Chronos_'+ident[:12]
    def row(n,c,p):return dict(name=n,class_name=c,pool_size=p,enabled=True,foreground=False,
        settings=[dict(target='Host',name='AutoCreateRole',value='0')] if n=='Chronos.Clarifiers' else [])
    value=dict(schema='chronos.workflow-optin-apply-scope.v1',deployment_id=ident,namespace='CHRONOS_'+ident[:12].upper(),
        operator=prefix+'_Operator',reader=prefix+'_Reader',origin=origin,application='/csp/chronos/',
        base_bundle_manifest_sha256=bundle,source_sha256={n:sha256((root/n).read_bytes()).hexdigest() for n in PINS},
        workflow_globals=GLOBALS,expected_before_items=[row(n,n,p) for n,p in BASE],
        expected_after_items=[row(n,n,p) for n,p in BASE]+[row(*v) for v in EXTRA],
        workflow_records=dict(role='Chronos.Clarifiers',user=prefix+'_Operator',membership_id='Chronos.Clarifiers||'+prefix+'_Operator',ranking=3,title=''),
        required_build='2026.3.0AI.154.0',production='Chronos.App.Production',
        security_accounts_to_create=[],security_roles_to_create=[],security_grants_to_add=[])
    return validate_scope(canonical(value))

def verify_scope_sources(scope,root=ROOT):
    need({n:sha256((root/n).read_bytes()).hexdigest() for n in PINS}==scope['source_sha256'],'SCOPE_SOURCE_CHANGED')

def quoted(value):
    return '"'+value.replace('"','""')+'"'

def program(action,scope,scope_sha,nonce,path=None):
    scope,_=validate_scope(canonical(scope))
    need(re.fullmatch('[a-f0-9]{64}',scope_sha) is not None and sha256(canonical(scope)).hexdigest()==scope_sha,'EXACT_SCOPE_SHA_REQUIRED')
    need(action in ('inspect','apply','status','readback','export'),'INVALID_ACTION')
    need(re.fullmatch('[a-f0-9]{32}',nonce) is not None,'INVALID_NONCE')
    ident=scope['deployment_id']; literal=quoted(canonical(scope).decode())
    code='set r=##class(Chronos.Deployment.NativeInstall).WorkflowDeliveryStatus("'+ident+'")\nif r.verified {\n'
    if action=='apply':
        code+='set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeWorkflowApply).Apply('+literal+',"'+scope_sha+'"))\n'
    elif action in ('inspect','readback'):
        code+='set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeWorkflowInspect).Inspect('+literal+','+('1' if action=='readback' else '0')+'))\n'
    elif action=='status':
        code+='set marker=$Get(^ChronosInstall("'+ident+'","workflowOptIn","state"))\n'
        code+='if marker="APPLIED_DISABLED" { set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeWorkflowInspect).Inspect('+literal+',1)) }\n'
        code+='elseif marker="" { set r={"status":"WORKFLOW_NOT_CONFIGURED","ready":false} }\n'
        code+='else { set r={"status":"WORKFLOW_PARTIAL_PRESERVED_NO_RETRY","ready":false} }\n'
    else:
        need(path is not None and str(path) in (str(proof_directory(scope)/'before.xml'),str(proof_directory(scope)/'after.xml')),'FIXED_EXPORT_PATH_REQUIRED')
        code+='if ##class(%File).Exists('+quoted(str(path))+') { set r={"status":"EXPORT_FILE_EXISTS_NO_OVERWRITE","ready":false} } else {\n'
        code+='new $Namespace set $Namespace="'+scope['namespace']+'"\n'
        code+='set sc=$System.OBJ.Export("Chronos.App.Production.cls",'+quoted(str(path))+')\n'
        code+='set r={"status":($Select($System.Status.IsOK(sc):"CALLBACK_EXPORTED",1:"CALLBACK_EXPORT_FAILED")),"ready":false}\n}\n'
    code+='}\n'
    block=' '.join(code.splitlines())
    return ('set r={"status":"WORKFLOW_COMMAND_FAILED","ready":false} try { '+block+
        ' } catch ex { set r={"status":"WORKFLOW_COMMAND_FAILED","ready":false} }\n'+
        'write !,"CHRONOS_NATIVE_INSTALL:'+nonce+':",r.%ToJSON(),!\nhalt\n')

def native(action,scope,scope_sha,*,authorize_id=None,path=None,run=subprocess.run,base=None):
    need(action!='apply' or authorize_id==scope['deployment_id'],'EXPLICIT_WORKFLOW_AUTHORIZATION_REQUIRED')
    need(re.fullmatch('[a-f0-9]{64}',scope_sha) is not None and sha256(canonical(scope)).hexdigest()==scope_sha,'EXACT_SCOPE_SHA_REQUIRED')
    env=dict(os.environ);env.pop('CHRONOS_WORKFLOW_OPTIN_APPROVED',None);env.pop('CHRONOS_INSTALL_APPROVED',None)
    if action=='apply':env['CHRONOS_WORKFLOW_OPTIN_APPROVED']=scope['deployment_id']+':'+scope_sha
    nonce=uuid.uuid4().hex
    try:
        result=run(['iris','session','IRIS','-U','%SYS'],input=program(action,scope,scope_sha,nonce,path),
            capture_output=True,text=True,env=env,timeout=180,check=False)
    except subprocess.TimeoutExpired:
        return dict(status='WORKFLOW_OUTCOME_UNCERTAIN_NO_RETRY',ready=False)
    need(result.returncode==0 and not result.stderr.strip(),'NATIVE_COMMAND_FAILED')
    return (base or sibling('native_install')).parse_output(result.stdout,nonce)

def proof_directory(scope):
    return Path('/durable/chronos')/scope['deployment_id']/'workflow-delivery'

def write_new(path,value):
    with path.open('xb') as stream:
        stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())

def callbacks(scope):
    directory=proof_directory(scope);check=sibling('workflow_callbacks').compare(
        (directory/'before.xml').read_bytes(),(directory/'after.xml').read_bytes())
    need(check.get('passed') is True and check.get('review_required') is False and
         check.get('other_class_deltas') in ([],['TimeChanged']) and
         all(check.get('callbacks_identical',{}).get(n) is True for n in ('OnStart','OnStop')),'CALLBACK_SOURCE_CHANGED')
    return check

def flow(action,scope,scope_sha,*,authorize_id=None,call=native):
    if action!='apply':
        result=call(action,scope,scope_sha)
        if result['status']=='OPTIN_APPLIED_DISABLED_READBACK':result['callbackComparison']=callbacks(scope)
        return result
    need(authorize_id==scope['deployment_id'],'EXPLICIT_WORKFLOW_AUTHORIZATION_REQUIRED')
    before=call('inspect',scope,scope_sha);need(before['status']=='OPTIN_PREFLIGHT_CLEAR','FRESH_CLEAR_PREFLIGHT_REQUIRED')
    area=proof_directory(scope)
    need(not any(p.is_symlink() for p in (area,*area.parents)),'LINKED_PROOF_DIRECTORY')
    area.mkdir(exist_ok=False)
    write_new(area/'intent.json',dict(scope_sha256=scope_sha,deployment_id=scope['deployment_id'],status='ONE_APPLY_INTENT_NO_RETRY'))
    need(call('export',scope,scope_sha,path=area/'before.xml')['status']=='CALLBACK_EXPORTED','CALLBACK_BASELINE_UNAVAILABLE')
    result=call('apply',scope,scope_sha,authorize_id=authorize_id);write_new(area/'apply-result.json',result)
    need(result['status']=='OPTIN_APPLIED_DISABLED' and result.get('ready') is False and
         result.get('accountsAndRouteDisabled') is True and type(result.get('modelCalls')) is int and result['modelCalls']==0 and
         all(type(result.get(k)) is int and result[k]==0 for k in ('securityAccountsAdded','securityRolesAdded','securityGrantsAdded')),
         'PARTIAL_OR_UNCERTAIN_OPTIN_NO_RETRY')
    after=call('readback',scope,scope_sha);write_new(area/'readback.json',after)
    need(after['status']=='OPTIN_APPLIED_DISABLED_READBACK','OPTIN_READBACK_UNVERIFIED')
    need(call('export',scope,scope_sha,path=area/'after.xml')['status']=='CALLBACK_EXPORTED','CALLBACK_READBACK_UNAVAILABLE')
    compared=callbacks(scope);write_new(area/'callback-comparison.json',compared)
    result['callbackComparison']=compared
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('plan','inspect','apply','status'))
    p.add_argument('--deployment-id');p.add_argument('--origin');p.add_argument('--application',default='/csp/chronos/')
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--scope',type=Path);p.add_argument('--scope-sha256')
    p.add_argument('--scope-out',type=Path);p.add_argument('--authorize-id');a=p.parse_args(argv)
    try:
        base=sibling('native_install')
        if a.action=='plan':
            base.validate(a.deployment_id,a.origin,a.application,a.manifest_sha256)
            base.verify_source(a.manifest_sha256,a.application)
            need(a.scope_out is not None,'NEW_SCOPE_OUTPUT_REQUIRED')
            scope,raw=make_scope(a.deployment_id,a.origin,a.manifest_sha256)
            with a.scope_out.open('xb') as stream:stream.write(raw)
            result=dict(status='WORKFLOW_SCOPE_PREPARED_NOT_APPLIED',ready=False,scope_sha256=sha256(raw).hexdigest(),deployment_id=scope['deployment_id'])
        else:
            need(a.scope is not None and a.scope_sha256 is not None,'REVIEWED_SCOPE_REQUIRED')
            scope,raw=validate_scope(a.scope.read_bytes())
            need(sha256(raw).hexdigest()==a.scope_sha256 and a.scope.read_bytes()==raw,'EXACT_CANONICAL_SCOPE_SHA_REQUIRED')
            need(scope['base_bundle_manifest_sha256']==a.manifest_sha256,'BASE_BUNDLE_CHANGED')
            base.verify_source(a.manifest_sha256,scope['application']);verify_scope_sources(scope)
            need(os.name=='posix','RUN_INSIDE_OWNED_LINUX_CONTAINER')
            need(a.action!='apply' or a.authorize_id==scope['deployment_id'],'EXPLICIT_WORKFLOW_AUTHORIZATION_REQUIRED')
            need(sibling('native_health').engine().get('ready') is True,'ENGINE_UNAVAILABLE')
            result=flow(a.action,scope,a.scope_sha256,authorize_id=a.authorize_id)
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,ET.ParseError) as error:
        code=str(error) if type(error) is ValueError and re.fullmatch('[A-Z_]{1,96}',str(error)) else 'COMMAND_UNAVAILABLE'
        result=dict(status='WORKFLOW_UNVERIFIED_PRESERVE_STATE_NO_AUTOMATIC_RETRY',code=code,ready=False)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status'] in ('WORKFLOW_SCOPE_PREPARED_NOT_APPLIED','OPTIN_PREFLIGHT_CLEAR','OPTIN_APPLIED_DISABLED','OPTIN_APPLIED_DISABLED_READBACK','WORKFLOW_NOT_CONFIGURED') else 1

if __name__=='__main__':raise SystemExit(main())
