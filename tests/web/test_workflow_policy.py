from pathlib import Path
import json,re,unittest
PATH=Path(__file__).resolve().parents[2]/'src/Chronos/Workflow/Policy.cls'
body=re.search(r'ClassMethod Parse\(body As %String, encoding As %String = "TEXT"\) As %String \[ Language = python \]\s*\{\n(.*?)\n\}',PATH.read_text(),re.S).group(1)
scope={};exec("def parse(body,encoding='TEXT'):\n"+body,scope);parse=scope['parse']

class WorkflowBodyPolicyTests(unittest.TestCase):
    def check(self,value,allowed):
        raw=value if type(value) is str else json.dumps(value)
        out=json.loads(parse(raw));self.assertIs(out['allowed'],allowed);return out
    def test_five_bounded_actions(self):
        values=[
            {'command':'START_CLARIFICATION','decisionId':'hold-1'},
            {'command':'READ_CLARIFICATION','decisionId':'hold-1'},
            {'command':'COMPLETE_CLARIFICATION','clarificationId':'clar-1','completionId':'completion-1','preference':'EARLIEST_ALLOWED','note':'The customer now prioritizes arrival time.'},
            {'command':'READ_CLARIFICATION_COMPLETION','clarificationId':'clar-1','completionId':'completion-1','preference':'EARLIEST_ALLOWED','note':'The customer now prioritizes arrival time.'},
            {'command':'REEVALUATE_CLARIFICATION','clarificationId':'clar-1','requestId':'decision-after-human-1'},
        ]
        for value in values:
            with self.subTest(command=value['command']):
                out=self.check(value,True);self.assertEqual(out['args'],{k:v for k,v in value.items() if k!='command'})
    def test_unsupported_authority_and_identity_are_rejected(self):
        for key,value in [('actor','principal-x'),('source',{}),('taskId','1'),('generation','g1'),('prepared',{}),('authorization','redacted-synthetic'),('url','https://example.invalid'),('role','admin')]:
            with self.subTest(key=key):self.check({'command':'START_CLARIFICATION','decisionId':'hold-1',key:value},False)
    def test_duplicate_keys_and_nonfinite_json(self):
        for value in ['{"command":"START_CLARIFICATION","decisionId":"one","decisionId":"two"}',
                      '{"command":"READ_CLARIFICATION","decisionId":NaN}',
                      '{"command":"READ_CLARIFICATION","decisionId":Infinity}']:
            with self.subTest(value=value):self.check(value,False)
    def test_ids_and_types(self):
        for value in ['',None,0,False,{},[], 'a'*129, '../other', 'x y','http://x','x\n','á']:
            with self.subTest(value=value):self.check({'command':'READ_CLARIFICATION','decisionId':value},False)
        self.check({'command':'REEVALUATE_CLARIFICATION','clarificationId':'c','requestId':'a'*64},True)
        self.check({'command':'REEVALUATE_CLARIFICATION','clarificationId':'c','requestId':'a'*65},False)
    def test_note_control_and_size_bounds(self):
        base={'command':'COMPLETE_CLARIFICATION','clarificationId':'c','completionId':'c1','preference':'CHEAPEST_ON_TIME','note':'Use the cheapest on-time option.'}
        self.check(base,True)
        for note in ['', 'x'*241, ' leading', 'trailing ', 'line\nbreak', 'back\\slash','zero\u200bwidth', '\ud800']:
            with self.subTest(note=repr(note)):self.check(dict(base,note=note),False)
        self.check(dict(base,note='x'*240),True)
    def test_never_accepts_effect_commands(self):
        for command in ['SEND','CONFIRM','ADMIT','PUT','RESERVE','REPLAY','RETRY_MODEL']:
            with self.subTest(command=command):self.check({'command':command,'decisionId':'d'},False)
    def test_invalid_or_large_body(self):
        for value in ['', '{}', 'null','[]','{"command":', ' '*4097]:self.check(value,False)
    def test_utf8_literal_and_json_escape_preserve_the_same_note(self):
        value={'command':'COMPLETE_CLARIFICATION','clarificationId':'c','completionId':'c1','preference':'CHEAPEST_ON_TIME','note':'Café order now prioritizes the cheapest on-time option.'}
        literal=json.dumps(value,ensure_ascii=False).encode('utf-8').hex()
        escaped=json.dumps(value,ensure_ascii=True).encode('utf-8').hex()
        a=json.loads(parse(literal,'UTF8_HEX'));b=json.loads(parse(escaped,'UTF8_HEX'))
        self.assertEqual(a,b);self.assertTrue(a['allowed']);self.assertEqual(a['args']['note'],value['note'])
    def test_invalid_utf8_hex_or_encoding_is_rejected(self):
        for value in ['ff','e9','00','x1','a','61'*4097]:
            with self.subTest(value=value[:30]):self.assertFalse(json.loads(parse(value,'UTF8_HEX'))['allowed'])
        self.assertFalse(json.loads(parse('{}','LATIN1'))['allowed'])

if __name__=='__main__':unittest.main(verbosity=2)
