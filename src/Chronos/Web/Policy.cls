/// Pure request validation, not authentication and not an installed HTTP route.
/// Expected origin/token must come from trusted server/session state, never JSON,
/// Host, forwarded headers or a caller-selected class. No request material logged.
Class Chronos.Web.Policy Extends %RegisteredObject
{
ClassMethod Validate(method As %String, contentType As %String, contentEncoding As %String, origin As %String, fetchSite As %String, csrf As %String, expectedOrigin As %String, expectedCSRF As %String, body As %String, family As %String = "approval") As %String [ Language = python ]
{
    import hmac,json,re
    from urllib.parse import urlsplit

    def deny(code):
        return json.dumps({'allowed':False,'code':code},separators=(',',':'))

    if family not in ('approval','decision'):return deny('SERVER_POLICY_UNAVAILABLE')
    commands=('DECISION','DECISION_DETAIL','DECISION_OPERATION','RESOLVE_DECISION') if family=='decision' else ('PREVIEW','READ','REJECT','CONFIRM','RECONCILE','READ_OPERATION','RECONCILE_OPERATION','PREVIEW_REQUEST','READ_PREPARATION','CLOSE_PREPARATION')

    # Also validate trusted configuration so an absent/malformed value cannot
    # accidentally allow an absent Origin/token. Local HTTP is loopback-only.
    values=(method,contentType,contentEncoding,origin,fetchSite,csrf,expectedOrigin,expectedCSRF,body)
    if not all(isinstance(value,str) for value in values):
        return deny('INVALID_REQUEST')
    try:
        target=urlsplit(expectedOrigin)
        if (not expectedOrigin.isascii() or len(expectedOrigin)>256
                or re.search(r'[\s\\]',expectedOrigin)
                or target.username is not None or target.password is not None
                or target.path or target.query or target.fragment
                or not target.hostname or target.port == 0
                or target.scheme not in ('http','https')
                or (target.scheme=='http' and target.hostname not in ('127.0.0.1','::1','localhost'))):
            return deny('SERVER_POLICY_UNAVAILABLE')
        # Reject trailing separators, ambiguous authority forms and noncanonical
        # case/default ports. Browsers serialize Origin in this canonical form.
        host='['+target.hostname+']' if ':' in target.hostname else target.hostname
        port=target.port
        canonical=target.scheme+'://'+host
        if port is not None and port != (443 if target.scheme=='https' else 80):
            canonical+=':'+str(port)
        if expectedOrigin!=canonical or not re.fullmatch(r'[a-z0-9.\-:]+',target.hostname):
            return deny('SERVER_POLICY_UNAVAILABLE')
    except ValueError:
        return deny('SERVER_POLICY_UNAVAILABLE')
    if not re.fullmatch(r'[0-9a-f]{64}',expectedCSRF):
        return deny('SESSION_POLICY_UNAVAILABLE')
    # All commands use POST, including reads, so no URL/query/cache stores IDs
    # or session tokens and there is one CSRF policy for the whole controller.
    if method!='POST':
        return deny('METHOD_NOT_ALLOWED')
    if origin!=expectedOrigin or fetchSite not in ('','same-origin'):
        return deny('CROSS_SITE_REQUEST')
    if not re.fullmatch(r'[0-9a-f]{64}',csrf) or not hmac.compare_digest(csrf,expectedCSRF):
        return deny('CSRF_REJECTED')
    if not re.fullmatch(r'application/json(?:\s*;\s*charset=utf-8)?',contentType,re.IGNORECASE):
        return deny('UNSUPPORTED_MEDIA_TYPE')
    if contentEncoding not in ('','identity'):
        return deny('UNSUPPORTED_ENCODING')
    # The HTTP adapter must bound the raw stream before decoding/allocating it.
    # This second bound protects direct/internal callers as well.
    try:
        if len(body)>4096 or len(body.encode('utf-8',errors='strict'))>4096:
            return deny('REQUEST_TOO_LARGE')
        def pairs(items):
            obj={}
            for key,value in items:
                if key in obj:
                    raise ValueError('DUPLICATE_FIELD')
                obj[key]=value
            return obj
        def constant(_):
            raise ValueError('NON_JSON_NUMBER')
        data=json.loads(body,object_pairs_hook=pairs,parse_constant=constant)
        if type(data) is not dict:
            return deny('INVALID_REQUEST')
        if type(data.get('command')) is not str or data['command'] not in commands:
            return deny('INVALID_REQUEST')
        correlated=data['command'] in ('PREVIEW_REQUEST','CLOSE_PREPARATION')
        expected={'command','id','requestId'} if correlated else {'command','id'}
        if set(data)!=expected:
            return deny('INVALID_REQUEST')
        if correlated and (type(data['requestId']) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',data['requestId'])):
            return deny('INVALID_REQUEST')
        if type(data['id']) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',data['id']):
            return deny('INVALID_REQUEST')
    except (ValueError,TypeError,RecursionError,UnicodeError):
        return deny('INVALID_REQUEST')
    field='requestId' if data['command']=='READ_PREPARATION' else 'decisionId' if family=='decision' or data['command']=='PREVIEW' or correlated else 'operationId' if data['command'] in ('READ_OPERATION','RECONCILE_OPERATION') else 'previewId'
    args={field:data['id']}
    if correlated:args['requestId']=data['requestId']
    return json.dumps({'allowed':True,'code':'VALID_REQUEST','command':data['command'],
                       'args':args},separators=(',',':'))
}
}
