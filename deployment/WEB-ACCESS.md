# Native web access (experimental installation step)

> Installation command order: follow [JURY-ROUTE.md](JURY-ROUTE.md). This is a
> component reference, not an additional setup pass. Do not prepare allowances or
> perform initial production start again after completing the canonical route.

**Development route with real authenticated browser evidence.** Recorded
installations have exercised activation, Reader/Operator login, denials, logout
and closure; the four-case flow 135 is summarized in [validation evidence](EVIDENCE.md#native-flow).
The earlier disabled-policy inspection 95 was a narrower historical check.
Later frozen 333 installation/browser observations are indexed in [EVIDENCE.md](EVIDENCE.md). Historical checks alone are not release approval.

This closes part of CHR-I03/U01/U05: an explicit route from disabled installation
to the authenticated review screen. It does not create a new account or change
roles, passwords, provider budgets or business decisions.

The executable examples below use the local E1 + C2v2 + loopback web + GPU layout.
Keep the complete file set chosen in [JURY-ROUTE.md](JURY-ROUTE.md): the examples already include conversation and GPU; do not append either twice. For cloud, follow [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) instead; do not retain the local-model/conversation/GPU overlay set. Use the original project, environment and bindings.


## 1. Choose local access before starting a NEW deployment

Use a NEW source bundle and matching installation, not an old installed receipt
with a different bundle hash. Follow [COMPOSE.md](COMPOSE.md) first. Choose an
unused host port and the exact origin before native installation; for example,
port52773 corresponds to `http://127.0.0.1:52773`. Use that same origin in every
installer/provider/web command. No helper rewrites an existing origin.

The opt-in `compose.web-local.yaml` adds one TCP mapping:
`127.0.0.1:CHRONOS_WEB_PORT -> IRIS:52773`. It exposes the IRIS web gateway to
this PC, including other IRIS web routes; it is not a path-filtering proxy.
It does not bind the LAN or provide remote HTTPS. The base file publishes no
ports. Do not widen the bind, expose the portal publicly or disable TLS checking.

Use the [canonical Compose step](JURY-ROUTE.md#2-fix-the-complete-compose-layout-before-engine-creation)
to set `CHRONOS_WEB_PORT` and the model, conversation and GPU variables
together, then verify the resolved configuration there. If you completed
that step, keep the same variables and files.

Include the same web override from the FIRST engine startup if browser access
will be needed. Native Chronos users and its application remain disabled until
their explicit setup steps. Review the instance's own account policy separately.

If using the local-model route, include `compose.local-model.yaml` and
`--profile local-model` consistently as described in [LOCAL-PROVIDER.md](LOCAL-PROVIDER.md).
The optional cloud route instead uses `compose.cloud.yaml` and its private
interactive startup from [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md); never run both
guards together. Its native/runtime proof is still pending.
Do not add the web mapping casually to an existing running deployment: Compose
may replace IRIS, and the model/guard share its network namespace. Controlled production stop/recovery has separate real evidence in
[NATIVE-RESUME.md](NATIVE-RESUME.md). Coordinated container replacement remains
unverified; the first-start provider helper is not a general restart tool.

## 2. Install and prepare the native workflow

Complete the matching disabled native installation, explicit local or cloud provider preparation,
immutable native configuration and initial production start. Use
[native provider status](NATIVE-PROVIDER.md); `RUNNING_NATIVE_ONLY` proves neither
model inference nor web login. Do not seed a timed synthetic case yet. Complete
private account setup, route activation and successful browser login first; the
case is created in step5 below. No recovery is automatically approved.

## 3. Set your own password privately in IRIS

The installer deliberately creates two scoped identities with discarded random
passwords. There is no published/default Chronos password.

Use the owned interactive IRIS console, with its normal input privacy:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec iris iris session IRIS -U %SYS
```

Run `do ^SECURITY`, choose **User setup → Edit user**, and select ONLY the
installed `Chronos_<first12deploymentid>_Operator` (or Reader for read-only use).

- Set and confirm your password directly in that console. Never place it in chat,
  CLI arguments, environment variables, JSON, shell history, screenshots or logs.
- Enable that selected user. After setting the password, clear the requirement
  to change it at the next login if IRIS offers that field.
- Keep the installer's exact roles, namespace and password/expiry policy.
  Do not add `%All`, new roles or escalation roles to bypass an error.
- Confirm only those intended account changes. Leave the other identity disabled
  unless it is independently needed and authorized.

The web helper does NOT read password/hash/salt properties, set/reset a password
or enable accounts. It checks that an installed identity is enabled with the
expected roles and no pending password-change flag. This is **not a login test**:
IRIS still applies its actual expiry, lockout and authentication policies.

Official references: [user management](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?CLASSNAME=Security.Users&LIBRARY=%25SYS)
and [application management](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?CLASSNAME=Security.Applications&LIBRARY=%25SYS).
These public class references are not proof of behavior on the required EA build.

## 4. Inspect, then explicitly enable the one Chronos route

Substitute the installed deployment ID, exact bundle digest and actual profile
digest. The origin/application must match the native installation.

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py status --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 PROFILE_SHA256
```

An authorized operator can then request activation with the same arguments:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py enable --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 PROFILE_SHA256 --authorize-id DEPLOYMENT_ID
```

The CLI prints a non-secret `REQUEST_ID_PREPARED` record BEFORE the native call.
Save that request ID. Supplying `--request-id` explicitly is also supported.
Opening requires matching source/installed spec, current route ownership,
private resources/roles/session policy, a privately prepared identity, closed
default namespace route and running recovered native production. It changes
only `Enabled` on the installed Chronos application and reads it back.

`WEB_ENABLED_LOGIN_UNVERIFIED` means the route is enabled, not that a browser
authenticated, the model worked, the workflow succeeded or the product is ready.
Every result retains `ready=false` and `login_tested=false`.

On a timeout, disconnect or invalid result, do not repeat with a new request ID.
Use `status` with the same parameters and `--request-id RECORDED_REQUEST_ID`.
Reusing an existing ID never issues another Modify. `REQUESTED` remains uncertain;
current enabled/disabled state is a separate observation and does not rewrite
the historic request as successful. `STATE_CHANGED_SINCE_REQUEST` means current
state no longer matches that earlier verified request.

## 5. Complete the actual browser proof

Open the exact configured origin plus `/csp/chronos/` and authenticate directly
in IRIS with the selected scoped account. First verify that the screen loads
and the session is usable. Only then follow [JURY-CASE.md](JURY-CASE.md) to prepare
the timed scenario and request one proposal. Use the resulting decision ID.
This avoids spending the case lifetime on password/provider/browser setup; it
does not renew an existing expired case. [JURY-ROUTE.md](JURY-ROUTE.md) gives the
complete order and its current native-validation limits.

Verify the session, current decision, source interpretation, alternatives and
separate proposed/authorized/executed/readback states. A Reader must not approve;
an Operator still needs explicit action-specific consent. Reload must recover
the original decision/operation; it must not dispatch another effect.
Test logout, revoked permission, stale approval and a denied cross-origin call
in the owned laboratory. Inspect desktop/mobile layouts and private error text.

The model's prose is not proof of acceptance or simulated delivery. Actual
readback and the case-specific effect must be checked separately. These remain
required native/browser tests, not results of the helper's unit tests.

## 6. Close access without depending on model readiness

Use `disable` with the same installation bindings and `--authorize-id`. It gets
a NEW request ID for this separate action, prints it before invocation, verifies
route ownership, updates only `Enabled=0` and reads it back. A broken model,
failed engine health gate or changed role policy must not prevent attempting to
close the still-owned route. A wrong installation/namespace/route binding blocks
the command instead of touching another application.

`WEB_DISABLED` describes the observed route state. This is not account deletion,
logout, production shutdown or cancellation of already-running work. Never
treat closing a web route as undoing a previously authorized business effect.

## Final-artifact acceptance still required

Recorded installations have exercised account/route activation, authenticated
Reader/Operator behavior and browser flows; see the evidence boundary at the top
and [native flow135 / lost-response138](EVIDENCE.md#native-flow). Older status-only
and compilation reports do not establish those later results by themselves.

For the final bundle, verify enable/disable readback, interruption before/after
Modify, repeat-ID behavior, changed role/application/mapping/profile rejection,
private login/expiry/logout, denied Reader approval, browser consent expiry and
the complete synthetic workflow. Preserve each test's actual scope and duration:
no one-hour session observation is claimed without measuring that interval.
Coordinated container replacement remains separate and unverified. Never treat
route closure as cancelling an already authorized business effect.
