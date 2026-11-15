/// Strict body projection only; authentication/origin/CSRF remain native CSP.
Class Chronos.Workflow.Policy Extends %RegisteredObject
{
ClassMethod Parse(body As %String, encoding As %String = "TEXT") As %String [ Language = python ]
{
    import json,re,unicodedata
    def deny(code='INVALID_WORKFLOW_REQUEST'):
        return json.dumps({'allowed':False,'code':code},sort_keys=True,separators=(',',':'))
    try:
        if encoding=='UTF8_HEX':
            if type(body) is not str or not 0<len(body)<=8192 or len(body)%2 or re.fullmatch(r'[0-9A-Fa-f]+',body) is None:return deny()
            body=bytes.fromhex(body).decode('utf-8','strict')
        elif encoding!='TEXT':return deny()
        if type(body) is not str or not 0<len(body.encode('utf-8'))<=4096:return deny()
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE_FIELD')
                out[key]=value
            return out
        def invalid(_):raise ValueError('NONFINITE_JSON')
        data=json.loads(body,object_pairs_hook=pairs,parse_constant=invalid)
        if type(data) is not dict or type(data.get('command')) is not str:return deny()
        command=data['command']
        fields={
            'START_CLARIFICATION':{'decisionId'},
            'READ_CLARIFICATION':{'decisionId'},
            'COMPLETE_CLARIFICATION':{'clarificationId','completionId','preference','note'},
            'READ_CLARIFICATION_COMPLETION':{'clarificationId','completionId','preference','note'},
            'REEVALUATE_CLARIFICATION':{'clarificationId','requestId'},
        }.get(command)
        if fields is None or set(data)!=fields|{'command'}:return deny()
        args={key:data[key] for key in sorted(fields)}
        for name,value in args.items():
            if type(value) is not str:return deny()
            if name in ('preference','note'):continue
            maximum=64 if name=='requestId' else 128
            if re.fullmatch(r'[A-Za-z0-9_.-]{1,'+str(maximum)+'}',value) is None:return deny()
        if command in ('COMPLETE_CLARIFICATION','READ_CLARIFICATION_COMPLETION'):
            if args['preference'] not in ('EARLIEST_ALLOWED','CHEAPEST_ON_TIME'):return deny()
            note=args['note']
            if not 1<=len(note)<=240 or note!=note.strip() or '\\' in note:return deny()
            if any(unicodedata.category(c).startswith('C') for c in note):return deny()
        return json.dumps({'allowed':True,'code':'WORKFLOW_REQUEST_VALID','command':command,'args':args},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError):
        return deny()
}
}
