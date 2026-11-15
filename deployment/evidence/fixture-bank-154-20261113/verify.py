"""Consistency of saved SDK captures only; never a fresh runtime assertion."""
from hashlib import sha256
from pathlib import Path
import json,re,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from chronos_transport.fixture_replay import FixtureCorpus,fixture_bank_digest,CASE_RULES,QUESTIONS

def verify():
    raw=(HERE/'corpus.json').read_bytes();data=json.loads(raw)
    allow=json.loads((HERE/'evidence-allowlist.json').read_bytes())
    summary=json.loads((HERE/'summary.json').read_bytes())
    fingerprint=sha256(raw).hexdigest()
    assert summary['corpus_sha256']==fingerprint and summary['fixture_sha256']==fixture_bank_digest()
    assert summary['sdk_calls']==8 and summary['workflow_executed'] is False and summary['accounts_changed']==0 and summary['business_effects']==0
    assert len(data['records'])==8 and len(allow)==8
    corpus=FixtureCorpus.from_bytes(raw,expected_sha256=fingerprint,fixture_sha256=fixture_bank_digest(),allowed_evidence=allow)
    expected={'e1-'+name for name,_,_ in CASE_RULES}|{'c2-question-'+str(i) for i in range(1,len(QUESTIONS)+1)}
    assert {r['record_id'] for r in data['records']}==expected
    records={r['record_id']:r for r in data['records']};seen=set()
    for capture in sorted((HERE/'captures').glob('*-result.json')):
        raw_capture=capture.read_bytes();saved=json.loads(raw_capture)
        assert saved['capture_kind']=='AI_HUB_SDK_DIRECT' and saved['workflow_executed'] is False
        assert saved['status']=='REAL_MODEL_CAPTURE' and re.fullmatch(r'[0-9]{1,18}',saved['ai_hub_session_id'])
        row=records[saved['record_id']];seen.add(saved['record_id'])
        assert saved['input_json']==row['input_json'] and saved['response_text']==row['response_text']
        assert sha256(saved['instructions'].encode()).hexdigest()==row['system_prompt_sha256']
        assert saved['captured_at']==row['provenance']['captured_at']
        evidence=sha256(raw_capture).hexdigest()
        assert row['provenance']['evidence_sha256']==evidence and allow[evidence]==saved['source_model']
        receipt=saved['receipt']
        assert receipt['version']==1 and receipt['finish_reason']=='stop' and receipt['model']==saved['source_model']
        assert receipt['response_contract']==row['response_contract']
        assert re.fullmatch(r'[a-f0-9]{64}',receipt['profile_sha256'])
        result=corpus.lookup(row['response_contract'],row['input_json'],row['system_prompt_sha256'])
        assert result.metadata['fresh_inference'] is False
    assert seen==expected
    return dict(status='SAVED_SDK_CAPTURES_CONSISTENT',records=8,corpus_sha256=fingerprint,
                fresh_runtime_execution=False,workflow_execution_proved=False)

if __name__=='__main__':
    try:result=verify()
    except (OSError,ValueError,KeyError,TypeError,AssertionError):
        print(json.dumps(dict(status='SAVED_CAPTURE_VALIDATION_FAILED',fresh_runtime_execution=False)))
        raise SystemExit(2)
    print(json.dumps(result,sort_keys=True))
