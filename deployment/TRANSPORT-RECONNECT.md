# Reconnect existing transports after an engine restart

Use this optional operational step after the original IRIS container has
restarted and its native recovery has been inspected. Keep the same container,
installation, data, profiles, quotas and request IDs. Replacing a container or
changing its Compose layout is a different, unqualified operation.

The model and E1/C2 transports share IRIS's network namespace. After an engine
container restart, a sidecar can still be running in the previous namespace.
`NetworkMode=container:<same ID>` alone does not prove that its current network
is connected. `RESUME_VERIFIED` describes native production recovery, not chat
or model connectivity.

## One explicit reconnection, without inference

Use the **original deployment's** `Dc` function, `$Python` and `$Id` from the
[live route](JURY-ROUTE.md) or [recorded route](RECORDED-REHEARSAL.md).
All selected sidecars must already exist and be running. The helper neither
creates containers nor starts stopped services. Use a new absolute evidence
directory outside the source bundle and provider-state directories.

Choose the original layout's services:

| Existing layout | `$ReconnectRoles` |
| --- | --- |
| Recorded, no model or GPU | `@('guard','conversation-guard')` |
| Local live model and C2 | `@('model','guard','conversation-guard')` |

For the live layout, recheck the original memory/GPU budget before restarting
the existing model service. Restoring transport can make queued requests
reachable again; it does not authorize new decisions or extend any allowance.
Do not choose the live row for a recorded deployment.

```powershell
$ReconnectRoles = @('guard','conversation-guard') # Recorded layout; select the matching row above.
$ReconnectProof = 'ABSOLUTE_PATH_TO_NEW_EVIDENCE_DIRECTORY'
$Docker = (Get-Command docker -CommandType Application -ErrorAction Stop).Source
$EngineId = (Dc ps --all --quiet iris).Trim()
if ($LASTEXITCODE -ne 0 -or $EngineId -notmatch '^[a-f0-9]{64}$') { throw 'Inspect the original engine identity.' }
$SidecarArgs = @()
foreach ($Role in $ReconnectRoles) {
    $ServiceId = (Dc ps --all --quiet $Role).Trim()
    if ($LASTEXITCODE -ne 0 -or $ServiceId -notmatch '^[a-f0-9]{64}$') { throw 'Inspect the original service identity.' }
    $SidecarArgs += @('--sidecar-id', $ServiceId)
}
& $Python -B deployment/transport_reconnect.py --docker $Docker --engine-id $EngineId --deployment-id $Id --authorize-engine-id $EngineId --output $ReconnectProof @SidecarArgs
if ($LASTEXITCODE -ne 0) { throw 'Preserve the evidence and inspect the same containers; do not repeat recovery or clear a reservation.' }
```

The helper verifies the bound project, full container IDs, images, source/state
mounts, resource limits and actual network namespaces. It restarts only the
selected running services that still use a different namespace. A durable,
exclusive reservation in `/durable/transport-reconnect` prevents concurrent
restarts for the same engine generation. It leaves the strict provider-state
directories intact. Partial results and uncertain responses are preserved; no
restart is automatically repeated and no reservation is automatically removed.

Require `TRANSPORT_CONNECTIVITY_VERIFIED_NOT_MODEL_INFERENCE` and matching final
namespace/endpoint observations for every selected service. Probes use only
loopback HTTP GET, without redirects or proxy settings. The guards must return
their expected `404 ROUTE_NOT_ALLOWED`; the model version endpoint is not an
inference test. A second check of services already connected requests no restart.

Then reopen the same authenticated decision and operation. Check the retained
receipt separately. This step never requests native production recovery, changes
accounts, prepares quotas, sends a completion or approves a recovery. It does
not by itself prove that a model answers correctly, a session is still valid,
or an operation has completed.

## Evidence boundary

On 15 November, real Docker tests reproduced the detached network and verified
reconnection with actual Chronos recorded E1/C2 transports. Both provider status
and allowances were unchanged; E1 remained 0/12 and C2 0/24. The second check
requested no restarts, and concurrent attempts to reserve the already claimed
generation were refused. All three owned test processes stopped with exit 0.
The parent process was Python, not IRIS. No inference or recorded completion was
requested. This is transport integration evidence, not the pending complete
native restart, Workflow or browser qualification. The local live model branch
also still needs integration validation on the final candidate.
