# Saved restart evidence: IRIS AI Hub build 154U

This packet exposes selected, privacy-reviewed observations from **11 November 2026**. It documents a completed synthetic-destination test of an **instrumented local copy of Chronos 1.0.2**, not a new execution of the public release and not a production delivery.

## What happened

1. Native AI Hub calls interpreted the same customer's preference. With A's queue at one minute the selected action was `RETRY_A`; with that queue at seven minutes it was `FAILOVER_B`. Interpretation came from the model; eligibility and selection remained deterministic code. The retained native session identifiers link these two decisions.
2. An authenticated Operator confirmed only B through the application API. The synthetic SQLite destination committed its acceptance. A lab-only adapter then waited for 45 seconds **after that commit and before returning the receipt to IRIS**. The adapter logged entry into `Submit` before destination deduplication, so that count would also include a duplicate dispatch attempt.
3. An independent destination read showed B accepted while IRIS still held `IN_FLIGHT` with an empty reference. The lab intentionally stopped the IRIS container **0.570 seconds** after the post-commit barrier marker. The retained exit was 137 with `OOMKilled=false`; this is an intentional failure injection, not a memory failure.
4. After restarting the lab, a pre-recovery read still showed the pending admission. Native production recovery opened a new generation and restored the original receipt. An authenticated Operator read the accepted result through the application.
5. The records agree on one operation, attempt, admission and receipt, **one recorded `Submit` entry and one accepted recovery effect**. A separate original synthetic attempt is not included in the recovery-effect count. Reader approval preparation and unresolved-original recovery were refused. Test accounts and route were disabled and all three services stopped cleanly at the end of that historical run.

## Check the retained observations

With Python 3.11 or newer, from this directory:

```sh
python -B verify.py
python -B -m unittest discover -s tests -v
```

`verify.py` checks the packet's canonical SHA-256 and cross-checks the state transitions, receipt and correlation identifiers, barrier timing, counts and closure. It is read-only, needs no packages, performs no network calls and starts no services. The negative tests alter in-memory copies to confirm that duplicate calls, changed receipts or attempts, an already-persisted reply, OOM, duplicate effects, late interruption and a consistently rewritten packet are rejected.

**This is a saved-evidence verifier, not a script that recreates the interruption in IRIS.** A passing result verifies the consistency and expected integrity of these retained records; it does not independently attest that the historical test occurred. Someone able to replace both this packet and its verifier can change the expected hash. Original-file hashes are provenance references, not signatures or proof of authenticity.

## Scope and provenance

`summary.json` is an allowlisted projection of the preserved private records. `source_sha256` retains the original file hashes. Its keys are paths relative to the original private run directory; they identify provenance and are not files shipped in this packet or paths to resolve beside `summary.json`. In particular, `stage/data/jury-challenge/submit-calls.jsonl` identifies the independent adapter-entry log. The source JSON files covered by the historical seal were checked against that seal before extraction. That raw `Submit` log is outside the historical seal's file list; its parsed rows were checked against the sealed final-destination record before extraction, and its own original-byte hash is retained here. Absolute paths, usernames, actor hashes, namespace, deployment bindings, environment details and authentication fields are omitted. Retained operation, attempt, admission, receipt and generation identifiers describe synthetic test entities.

The instrumentation's original SHA-256 is retained under `support/challenge_fault.py`; that private instrumentation and its machine-specific runner are not shipped here. This packet does not assert that the instrumented tree is byte-identical to the public release. It does not cover real carriers, physical delivery, failover between servers or every interruption window. A was a proposal only; B was the only recovery executed. Approval in this test was an automated authenticated Operator API action, not a recorded human click or a new visual-interface audit.

The two A/B examples show those specific decisions. They are not a general model benchmark, a statistical claim of superiority over rules or evidence of improved real-world delivery times.
