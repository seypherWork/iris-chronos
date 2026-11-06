# Resume and recovery of the owned IRIS production

These console commands operate on one installed Chronos namespace. They do not
enable accounts or web access, start a model, reset a quota or approve a case.
Starting a production can resume queued interoperability messages. The existing
admission fences must remain intact; reconciliation queries a destination rather
than automatically resending an uncertain business operation.

**Evidence boundary:** the phased crash-recovery implementation is a development
candidate. Its CLI boundary tests are simulated; separately, controlled real
engine-interruption tests 149/150 passed on installation 145. See the
[matching evidence and limits](EVIDENCE.md#engine-interruption-and-delivery-state)
before treating a particular bundle as verified. Earlier clean-resume and
journal-durability results do not automatically validate changed source.

## Common preparation

Start only the owned IRIS container using its existing Compose configuration.
Retain its original source bundle, provider profile, database mappings and data.
Run `/usr/bin/python3 -B /opt/chronos/deployment/native_resume.py` inside the
container as `irisowner`, for example through `docker compose ... exec -T iris`.
Every command takes the original `--deployment-id`, `--origin`, `--application`,
`--manifest-sha256` and `--profile-sha256` arguments. Do not substitute another
installation's values.

The CLI verifies the installed source before loading trusted console classes.
`inspect` and `status` can compile those helpers but do not request lifecycle
operations. They remove inherited mutation grants. Mutations use an exact
installation, source, profile, binding, request and generation grant; recovery
also binds the specific action. A clean-resume grant cannot authorize recovery.

Run `inspect` first and retain its response. Generate one random 32-character
lowercase hexadecimal request ID for a new eligible generation, for example
with Python `uuid.uuid4().hex`. Keep that ID through any uncertainty. Never clear
the initial-start fence, generation index or request history to get another try.

## Clean stop

Only `STOPPED_RESUME_AVAILABLE` permits `resume`. It requires native stopped
state and the actual Chronos stopped callback, not a fabricated boot record.
Use the common arguments plus:

```
resume --request-id REQUEST_ID --expected-generation OBSERVED_GENERATION --authorize-id DEPLOYMENT_ID
```

The request is committed and flushed to the journal before the single
`StartProduction` call. Repeating that request reads its receipt and never starts
again. Historical legacy clean-resume receipts remain separate from recovery.

## Crash recovery

Only `CRASH_RECOVERY_AVAILABLE` permits a new `recover` request. The native
production must be troubled and named exactly `Chronos.App.Production`; its
generation must be unclaimed and not ready. Use:

```
recover --request-id REQUEST_ID --expected-generation OBSERVED_GENERATION --authorize-id DEPLOYMENT_ID
```

Recovery records and flushes each phase before proceeding:

1. `RECOVER_REQUESTED`: before one documented `Ens.Director.RecoverProduction`.
2. `RECOVERED_OBSERVED`: native stopped or suspended state with the original generation and
   unchanged configuration has been observed. This does not prove which actor
   caused the stop.
3. `START_REQUESTED`: before one `StartProduction` call.
4. `VERIFIED`: a different ready native generation has been observed and the
   receipt flushed. This does not establish model readiness or delivery.

No path calls `CleanProduction`, purges queues, fakes `OnStop`, resets a fence,
reconstructs lost authorization or resends a business operation. Do not use this
to repair an old deployment that lost its admission history.

## Lost response or interrupted recovery

First use the same request ID, with no expected-generation argument:

```
status --request-id REQUEST_ID
```

`status` and a repeated `recover` never repeat either lifecycle call. A timeout
does not prove cancellation. Keep the receipt and inspect its kind and phase.

For an existing recovery receipt, `resolve-recovery` can record a newly observed
condition without calling RecoverProduction or StartProduction. It is an
authorized receipt mutation, not a completely read-only command:

```
resolve-recovery --request-id REQUEST_ID --expected-generation ORIGINAL_GENERATION --authorize-id DEPLOYMENT_ID
```

If the stored phase is `RECOVER_REQUESTED` and the production is now stopped or suspended in
the original generation, resolution may record `RECOVERED_OBSERVED`. If the phase
is `START_REQUESTED` and a new generation is ready, it may record `VERIFIED`.
Resolution proves the observed condition, not causal ownership of an earlier
call. All source, installation and configuration bindings must still match.

Only `RECOVERED_OBSERVED` can be continued explicitly:

```
continue-recovery --request-id REQUEST_ID --expected-generation ORIGINAL_GENERATION --authorize-id DEPLOYMENT_ID
```

This rechecks the exact previously observed stopped/suspended state and configuration, flushes `START_REQUESTED`, then
requests Start once. **An existing `START_REQUESTED` never requests Start again,
even if native state still appears stopped.** If recovery is still troubled or
the outcome cannot be established, retain uncertainty and investigate. These
commands do not promise automatic recovery from every possible interruption.

## Reading the result

| Field or status | Meaning |
|---|---|
| `request_kind` | `none`, clean `resume`, or phased `recover`; kinds cannot be exchanged. |
| `recovery_phase` | Durable recovery progress; `NONE` for clean resume. |
| `start_requested_this_call`, `recover_requested_this_call` | Actual calls in this invocation, never inferred from a historical phase. Null after an untrusted transport outcome means unknown. |
| `RESUME_VERIFIED` | A verified new native generation was recorded. It may be historical; inspect current readiness and generation separately. |
| `REQUESTED_OUTCOME_UNCERTAIN` | Preserve the request and consult its phase. It is not permission to retry with a new ID. |
| `GENERATION_ALREADY_REQUESTED` | Consult the existing `generation_request_id`; another ID cannot bypass it. |
| `REQUEST_NOT_FOUND` | No receipt observed at that instant; not proof that an earlier process has ended. |
| `BUSY`, `NOT_RESUMABLE`, rejection | Inspect and preserve state. No forceful fallback occurs. |
| `OUTCOME_UNCERTAIN_USE_STATUS` or changed provider | Transport or binding was untrusted. Keep the same ID and inspect. |
| `DURABILITY_UNCONFIRMED` | The journal barrier was not confirmed. Later lifecycle I/O is withheld; a committed write is not falsely described as rolled back. |

Post-start observations share one bounded 30-second monotonic budget. Busy
observations clear previous readiness; polling never repeats Start. The
90-second client timeout is not server-side cancellation. Every response keeps
`ready=false` and `model_tested=false`; `runtime_ready` describes only native
production readiness. A functioning model, a valid decision, authorization,
destination acceptance and physical delivery require their own evidence.

## Suspended production after recovery

Real AI Hub154 interruption test144 returned Suspended (3) after successful
RecoverProduction, with the same generation and all configuration hashes intact.
Stopped-only validation correctly withheld Start but prevented useful recovery.
Candidate145 records `RECOVERED_OBSERVED` together with the exact native state
(Stopped2 or Suspended3) before authorizing Start. Suspended requires the exact
Chronos production name. A change between those states requires investigation,
not silent continuation. Native clean-resume behavior remains stopped-only.

[InterSystems documents](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=EGDV_testing)
that a suspended production can be started to process its remaining messages.
Chronos does not clear those messages. This is not a guarantee that every cause
of suspension is resolved. The failed144 receipt and bundle remain unchanged;
145 needs its own actual native proof.
