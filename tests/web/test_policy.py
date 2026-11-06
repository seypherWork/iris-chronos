"""Exercise the exact Embedded Python method; native execution is separate."""
import json
from pathlib import Path
import textwrap
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'src/Chronos/Web/Policy.cls'
source=SOURCE.read_text(encoding='utf-8')
body=source.split('[ Language = python ]\n{\n',1)[1].rsplit('\n}\n}',1)[0]
env={}
exec('def validate(method,contentType,contentEncoding,origin,fetchSite,csrf,expectedOrigin,expectedCSRF,body,family="approval"):\n'+textwrap.indent(textwrap.dedent(body),'    '),env)
validate=env['validate']


class PolicyTests(unittest.TestCase):
    def request(self,**changes):
        args=dict(method='POST',contentType='application/json',contentEncoding='',
                  origin='https://localhost:52820',fetchSite='same-origin',csrf='a'*64,
                  expectedOrigin='https://localhost:52820',expectedCSRF='a'*64,
                  body='{"command":"CONFIRM","id":"preview-01"}')
        args.update(changes)
        return json.loads(validate(**args))

    def test_all_commands_translate_only_ids(self):
        for command in ('PREVIEW','READ','REJECT','CONFIRM','RECONCILE'):
            with self.subTest(command=command):
                result=self.request(body=json.dumps({'command':command,'id':'safe_01.x'}))
                self.assertEqual(result,dict(allowed=True,code='VALID_REQUEST',command=command,
                    args={('decisionId' if command=='PREVIEW' else 'previewId'):'safe_01.x'}))

    def test_method_and_origin_are_required(self):
        for changes in ({'method':'GET'},{'method':'OPTIONS'},{'method':'post'},
                        {'origin':''},{'origin':'null'},{'origin':'https://localhost:52821'},
                        {'origin':'https://evil.example'},{'fetchSite':'same-site'},
                        {'fetchSite':'cross-site'},{'fetchSite':'none'}):
            with self.subTest(changes=changes):self.assertFalse(self.request(**changes)['allowed'])

    def test_decision_route_is_separate_and_never_accepts_authority(self):
        for command in ('DECISION','DECISION_DETAIL','RESOLVE_DECISION'):
            body=json.dumps({'command':command,'id':'decision-01'})
            result=self.request(body=body,family='decision')
            self.assertEqual(result,dict(allowed=True,code='VALID_REQUEST',command=command,args={'decisionId':'decision-01'}))
            self.assertFalse(self.request(body=body)['allowed'])
            for change in ({'csrf':'b'*64},{'origin':'https://evil.example'},{'method':'GET'}):
                self.assertFalse(self.request(body=body,family='decision',**change)['allowed'])
            for field in ('orderId','shipmentVersion','mode','generation','family','actor','deadlineUS','root','namespace','module','record','decisionJSON','prepared'):
                self.assertFalse(self.request(body=json.dumps({'command':command,'id':'decision-01',field:'forged'}),family='decision')['allowed'])
        for command in ('PREVIEW','READ','REJECT','CONFIRM','RECONCILE','PROPOSE','DECISION,RESOLVE_DECISION'):
            self.assertFalse(self.request(body=json.dumps({'command':command,'id':'decision-01'}),family='decision')['allowed'])
        self.assertEqual(self.request(family='other')['code'],'SERVER_POLICY_UNAVAILABLE')

    def test_configuration_fails_closed(self):
        for origin in ('','null','http://example.com','https://localhost/','https://localhost?',
                       'https://localhost#','https://user@localhost','https://localhost:bad',
                       'https://localhost:0','https://localhost:443','https://LOCALHOST',
                       'https://local\nhost','https://localhost\\@evil.example'):
            with self.subTest(origin=origin):
                self.assertEqual(self.request(expectedOrigin=origin,origin=origin)['code'],'SERVER_POLICY_UNAVAILABLE')

    def test_loopback_http_is_explicit_and_exact(self):
        for origin in ('http://localhost:52820','http://127.0.0.1:52820','http://[::1]:52820'):
            with self.subTest(origin=origin):self.assertTrue(self.request(expectedOrigin=origin,origin=origin)['allowed'])
        self.assertFalse(self.request(expectedOrigin='http://localhost.evil:52820',origin='http://localhost.evil:52820')['allowed'])

    def test_csrf_is_not_reflected_and_cannot_be_empty(self):
        for changes in ({'csrf':''},{'csrf':'b'*64},{'expectedCSRF':''},
                        {'expectedCSRF':'a'*63},{'csrf':'A'*64},{'csrf':'a'*10000}):
            with self.subTest(fields=list(changes)):
                result=self.request(**changes)
                self.assertFalse(result['allowed'])
                self.assertEqual(set(result),{'allowed','code'})

    def test_media_and_encoding(self):
        self.assertTrue(self.request(contentType='Application/JSON; charset=UTF-8')['allowed'])
        self.assertTrue(self.request(fetchSite='')['allowed']) # mandatory exact Origin + token remain
        for changes in ({'contentType':'text/plain'},{'contentType':'application/json;charset=latin1'},
                        {'contentType':'application/json;evil=1'},{'contentEncoding':'gzip'}):
            self.assertFalse(self.request(**changes)['allowed'])

    def test_duplicates_including_escaped_keys_are_rejected(self):
        for body in ('{"command":"READ","command":"CONFIRM","id":"p"}',
                     '{"command":"CONFIRM","id":"p","i\\u0064":"q"}'):
            self.assertFalse(self.request(body=body)['allowed'])

    def test_invalid_or_ambiguous_json(self):
        for body in ('{}','[]','null','true','NaN','Infinity','{"command":"READ","id":NaN}',
                     '{"command":"READ","id":"p"}{}','{"command":"READ","id":"p",}',
                     '{"command":"READ","id":"p"/*x*/}','\ufeff{"command":"READ","id":"p"}',
                     '['*1500+']'*1500):
            with self.subTest(body=body[:50]):self.assertFalse(self.request(body=body)['allowed'])

    def test_no_authority_fields_or_nonstring_ids(self):
        for value in (None,True,1,[],{},'', 'x'*129, '../escape','bad\nline','é','\ud800'):
            self.assertFalse(self.request(body=json.dumps({'command':'CONFIRM','id':value}))['allowed'])
        for field in ('actor','sessionBinding','claimId','operationId','generation','csrf','option','deadline'):
            self.assertFalse(self.request(body=json.dumps({'command':'CONFIRM','id':'p',field:'injected'}))['allowed'])

    def test_size_bound_counts_utf8_bytes(self):
        self.assertEqual(self.request(body=' '*4097)['code'],'REQUEST_TOO_LARGE')
        self.assertEqual(self.request(body='é'*2049)['code'],'REQUEST_TOO_LARGE')
        self.assertFalse(self.request(body='\ud800')['allowed'])

    def test_preparation_commands_accept_only_public_correlation(self):
        for command in ('PREVIEW_REQUEST','CLOSE_PREPARATION'):
            body=json.dumps({'command':command,'id':'decision-48','requestId':'request-48'})
            self.assertEqual(self.request(body=body),dict(allowed=True,code='VALID_REQUEST',command=command,
                args={'decisionId':'decision-48','requestId':'request-48'}))
            self.assertFalse(self.request(body=body,family='decision')['allowed'])
        self.assertEqual(self.request(body='{"command":"READ_PREPARATION","id":"request-48"}'),
            dict(allowed=True,code='VALID_REQUEST',command='READ_PREPARATION',args={'requestId':'request-48'}))

    def test_correlation_required_exact_and_never_a_grant(self):
        for command in ('PREVIEW_REQUEST','CLOSE_PREPARATION'):
            self.assertFalse(self.request(body=json.dumps({'command':command,'id':'d'}))['allowed'])
            for value in (None,True,1,[],{},'', 'x'*129, '../escape','bad\nline','é','\ud800'):
                self.assertFalse(self.request(body=json.dumps({'command':command,'id':'d','requestId':value}))['allowed'])
            for field in ('actor','sessionBinding','generation','previewId','preparationGranted','claimId','option','payload'):
                data={'command':command,'id':'d','requestId':'r',field:'forged'}
                self.assertFalse(self.request(body=json.dumps(data))['allowed'])
        for command in ('PREVIEW','READ','CONFIRM','REJECT','RECONCILE','READ_PREPARATION','DECISION','DECISION_DETAIL','RESOLVE_DECISION'):
            family='decision' if command in ('DECISION','DECISION_DETAIL','RESOLVE_DECISION') else 'approval'
            self.assertFalse(self.request(body=json.dumps({'command':command,'id':'d','requestId':'r'}),family=family)['allowed'])

    def test_correlation_duplicates_escaping_and_order(self):
        for body in (
            '{"command":"PREVIEW_REQUEST","id":"d","requestId":"r","requestId":"s"}',
            '{"command":"PREVIEW_REQUEST","id":"d","requestId":"r","request\\u0049d":"s"}',
            '{"command":"PREVIEW_REQUEST","id":"d","requestId":"r","i\\u0064":"e"}'):
            self.assertFalse(self.request(body=body)['allowed'])
        result=self.request(body='{"request\\u0049d":"r","i\\u0064":"d","comm\\u0061nd":"PREVIEW_REQUEST"}')
        self.assertEqual(result['args'],{'decisionId':'d','requestId':'r'})

    def test_preparation_requests_keep_csrf_origin_method_and_size_guards(self):
        for command in ('PREVIEW_REQUEST','READ_PREPARATION','CLOSE_PREPARATION'):
            data={'command':command,'id':'d'}
            if command!='READ_PREPARATION':data['requestId']='r'
            body=json.dumps(data)
            for change in ({'csrf':'b'*64},{'origin':'https://foreign.example'},{'method':'GET'},{'fetchSite':'cross-site'},{'contentType':'text/plain'}):
                self.assertFalse(self.request(body=body,**change)['allowed'])
            self.assertEqual(self.request(body=body+' '*4097)['code'],'REQUEST_TOO_LARGE')


if __name__=='__main__':unittest.main(verbosity=2)


class OperationPolicyTests(unittest.TestCase):
    request = PolicyTests.request
    def test_operation_read_and_query_are_exact_guarded_ids(self):
        for command,family,field in (
            ('DECISION_OPERATION','decision','decisionId'),
            ('READ_OPERATION','approval','operationId'),
            ('RECONCILE_OPERATION','approval','operationId')):
            body=json.dumps({'command':command,'id':'fixed-op-114'})
            self.assertEqual(self.request(body=body,family=family),
                dict(allowed=True,code='VALID_REQUEST',command=command,args={field:'fixed-op-114'}))
            for change in ({'method':'GET'},{'origin':'https://evil.example'},{'csrf':'b'*64}):
                self.assertFalse(self.request(body=body,family=family,**change)['allowed'])
            for extra in ('operationId','orderId','actor','target','payload','dispatchGranted','requestId'):
                self.assertFalse(self.request(body=json.dumps({'command':command,'id':'fixed-op-114',extra:'forged'}),family=family)['allowed'])
            self.assertFalse(self.request(body=body,family='approval' if family=='decision' else 'decision')['allowed'])

