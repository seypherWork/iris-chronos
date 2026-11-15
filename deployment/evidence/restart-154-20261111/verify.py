"""Verify retained historical evidence. Does not start or reproduce IRIS."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys

EXPECTED_CANONICAL_SHA256 = 'cf5493b69349f10a09bed5ce246d4a867bd85b40aaceabfda0d7acab109b0d60'


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def verify_records(data):
    """Cross-check observations; integrity is separately checked by verify_summary."""
    check(data['schema'] == 'chronos.saved-restart-evidence.v1', 'unsupported schema')
    check(data['base_release'] == '1.0.2', 'unexpected baseline')
    before, cut = data['before_cut'], data['cut']
    barrier, original = before['barrier'], before['barrier']['receipt']
    delay = datetime.fromisoformat(cut['FinishedAt'].replace('Z', '+00:00')).timestamp() - barrier['start_utc']
    check(cut['started_at_before_cut'] == cut['StartedAt'], 'pre-cut container start changed')
    check(cut['Running'] is False and cut['ExitCode'] == 137 and cut['OOMKilled'] is False, 'expected intentional stop, not OOM')
    check(0 <= delay < barrier['timeout_seconds'] == 45, 'stop occurred outside the receipt barrier')
    check(round(delay, 3) == 0.570, 'cut timing differs from retained result')
    pending = [before['iris'], data['after_restart_before_recovery']]
    check(all(row['state'] == 'IN_FLIGHT' and row['reference'] == '' for row in pending), 'receipt had already reached IRIS')
    recovered, final = data['recovered_operation'], data['destination_final']
    for key in ('operationId', 'attemptId', 'admissionId'):
        check(all(row[key] == barrier[key] for row in pending + [recovered]), 'recovery identity changed: ' + key)
    for row in [before['destination_recovery'], final['accepted'], original, data['operator_readback']]:
        check(all(row[key] == recovered[key] for key in ('operationId', 'attemptId')), 'destination/readback identity mismatch')
    check(before['destination_recovery']['state'] == 'ACCEPTED' and original['status'] == 'ACCEPTED', 'destination had not accepted before stop')
    check(recovered['state'] == final['accepted']['state'] == data['operator_readback']['state'] == 'ACCEPTED', 'not accepted after recovery')
    check(all(row['target'] == 'B' for row in pending + [recovered, before['destination_recovery'], final['accepted'], original]), 'recovery target changed')
    check(recovered['lastReceiptId'] == original['receiptId'], 'receipt identity changed')
    check(recovered['reference'] == original['reference'] == data['operator_readback']['reference'] and original['reference'], 'receipt reference changed')
    check(len(final['rawCalls']) == len(data['raw_submit_log']) == 1 and final['rawCalls'] == data['raw_submit_log'], 'expected one recorded Submit entry')
    check(all(final['rawCalls'][0][key] == recovered[key] for key in ('operationId', 'attemptId', 'admissionId')), 'raw call identity mismatch')
    check(final['accepted']['submits'] == final['accepted']['attempts'] == 1, 'expected one accepted recovery effect and attempt')
    check(before['destination_recovery']['submits'] == before['destination_recovery']['attempts'] == 1, 'before-cut destination counts differ')
    resume = data['resume']
    check(resume['status'] == 'RESUME_VERIFIED' and resume['recovery_phase'] == resume['request_state'] == 'VERIFIED' and resume['runtime_ready'] is True, 'production recovery was not verified')
    check(data['pre_resume_inspection']['status'] == 'CRASH_RECOVERY_AVAILABLE', 'missing pre-resume observation')
    check(data['pre_resume_inspection']['current_generation'] == resume['previous_generation'], 'prior production generation changed')
    check(resume['current_generation'] == resume['recorded_generation'] != resume['previous_generation'], 'production generation was not renewed')
    check(resume['model_tested'] is False, 'recovery claim must not imply a new model test')
    check(data['operator_readback']['quarantined'] is False and data['operator_readback']['dispatchGranted'] is False, 'readback granted dispatch')
    check(data['hold'] == {'deterministic_code': 'ACCEPTANCE_UNRESOLVED', 'dispatch_authorized': False, 'inference_may_have_run': False, 'recovery_submissions': 0}, 'uncertain-original safety result changed')
    check(data['permission_checks']['hold']['code'] == 'DECISION_NOT_ACTIONABLE' and data['permission_checks']['reader']['code'] == 'PERMISSION_DENIED', 'expected permission refusal missing')
    for name, action in [('economy', 'RETRY_A'), ('queue_inventory', 'FAILOVER_B')]:
        record = data['decisions'][name]
        check(record['action'] == action and record['interpreted_preference'] == 'CHEAPEST_ON_TIME', 'decision changed')
        check(record['native_trace']['aiHubSessionId'] and record['native_trace']['interopSessionId'], 'native trace identifier missing')
        check(record['attribution'] == {'interpretationOrigin': 'MODEL', 'selectionOrigin': 'DETERMINISTIC_CODE'}, 'agent/selector attribution changed')
    check(set(data['closure']['access']) == {'reader', 'operator', 'route'} and set(data['closure']['access'].values()) == {'disabled'}, 'access was not closed')
    check(set(data['closure']['services']) == {'guard', 'model', 'iris'}, 'unexpected closure service set')
    check(all(row == {'running': False, 'exit': 0, 'oom': False} for row in data['closure']['services'].values()), 'service did not stop cleanly')
    return {'status': 'PASS', 'scope': 'retained records only; no IRIS execution', 'observed_date_utc': data['observed_date_utc'], 'cut_seconds_after_acceptance_marker': round(delay, 3), 'operation_count': 1, 'attempt_count': 1, 'admission_count': 1, 'receipt_count': 1, 'recorded_submit_entries': 1, 'accepted_recovery_effects': 1}


def verify_summary(data):
    check(sha256(canonical(data)).hexdigest() == EXPECTED_CANONICAL_SHA256, 'packet integrity mismatch')
    return verify_records(data)


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).with_name('summary.json')
        if len(sys.argv) > 2:
            raise ValueError('usage: python verify.py [summary.json]')
        print(json.dumps(verify_summary(json.loads(path.read_bytes())), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'status': 'FAIL', 'reason': str(error)}))
        raise SystemExit(1)
