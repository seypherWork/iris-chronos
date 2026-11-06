# Read-only installation preflight

This tool inspects the intended IRIS target before installation. It does not
install Chronos, reserve names, compile classes, start a production/model, create
an allowance, change security policy or grant permission to proceed.

The current source targets the required Linux container build
IRIS AI Hub 2026.3.0AI.154.0 and an already-running owned container with no published
Docker ports. The Windows project and data paths remain on D:.
The layout 4 catalogue adds a separate resource for the temporary database.
Local checks compare this change against a saved build 154 inspection of the
previous 24-name layout. The revised auxiliary query still needs a run on IRIS.

For a new Compose installation, verify the staging tree before startup, then
use `deployment/native_install.py inspect` inside that engine as documented in
[COMPOSE.md](COMPOSE.md). This auxiliary tool cannot establish its mounts or
installation intent and is not the post-start jury installation command.

## Inputs and trust boundaries

Use the exact source bundle and its separately pinned manifest SHA-256. Supply
the same reviewed config/profile that produced the installation plan. The CLI
recomputes that plan and verifies package/dependency hashes; it does not trust an
edited plan JSON as authority.

The container must be explicitly pinned by full64-character ID, image SHA and
StartedAt value from the selected owned container. The CLI inspects only these
fields, running status and port bindings, never its environment or credentials.
A restart, changed image, exposed port or mismatched identity stops the check.
It must use the trusted installed Docker executable.

Illustrative invocation (replace placeholders; this is not an executable jury
quickstart or an authorization to configure accounts):

    python -B tools/installation_preflight.py \
      --bundle D:/path/to/verified-source-bundle \
      --bundle-sha256 <pinned-manifest-sha256> \
      --config D:/path/to/reviewed-config.json \
      --profile D:/path/to/reviewed-profile.json \
      --docker <absolute-path-to-trusted-docker.exe> \
      --container-id <full-owned-container-id> \
      --expected-image sha256:<pinned-image-id> \
      --expected-started-at <observed-start-time> \
      --output D:/path/to/new-preflight-report.json

The command above uses illustrative line continuation. On Windows PowerShell,
put it on one line or use PowerShell continuation syntax. Existing output files
are refused before any native read. No credential belongs in these inputs.

## What is checked

The native query lists 25 targets, covering one namespace, three database names,
two users, four roles, four private resources, two shared resources, two required
system resources, two applications and five directories. The temporary database
has its own private resource.

- Existing names/directories that should be new are conflicts.
- Shared Chronos_Read/Chronos_Approve must match the documented description and
  have no public permission. Their absence is an explicit proposal for creation,
  which still requires approval.
- Required Embedded Python and IRISSYS resources must exist.
- Missing objects are recognized only by the concrete missing-object status
  verified for build154. Other lookup failures are errors, never availability.
- Every lookup resets local variables and catches exceptions. Native console
  errors, stderr, missing rows, duplicate targets or inconsistent status reject
  the observation. No account property/password is read or printed.

Result names are intentionally limited:
PREFLIGHT_NAMES_CLEAR_FOR_REVIEW means only that this snapshot found no naming
or shared-resource conflict. It always retains ready_for_apply=false.
PREFLIGHT_CONFLICTS_OR_ERRORS and PREFLIGHT_REJECTED prohibit proceeding.

## Known catalogue versus installation proof

The v3 configuration plan declares the layout 4 catalogue for the build 154
native installer. The result reports `checked_scope=LISTED_25_NAMES_ONLY` and retains
`native_scope_complete=false` and `ready_for_apply=false`: a name inventory does
not prove all mappings, properties, engine health, installation intent or runtime
behavior. Missing/old v1/v2 scope declarations are rejected.

Earlier18/26-check reports retain their original scope and unchanged
files. They are not retroactively upgraded by changing today's source.

## What remains unverified

A new check is required immediately before an authorized mutation. These reads
are not a transactional reservation. Mount mapping, networking/TLS, compilation,
browser identity/login, model compatibility and the installer apply path are
not established by a clear snapshot.

The fresh-path plan remains a pre-staging check and rejects existing data.
Alternatively, use --stage-root with the new staging helper's output. That path
requires its pinned bundle, matching profile/config/receipt, the same physical
empty data AND guard directories and no app/runtime directory. Once Compose
writes `data/iris`, pristine verification must fail. Use native_install.py inspect
on that actual engine; never erase/relabel data to reuse the pre-start verifier.
This auxiliary route does not accept arbitrary pre-existing data. Do not combine --stage-root with --bundle/--config/--profile.

For staged mode, supply --stage-root, --bundle-sha256, the same pinned Docker
identity arguments and a new --output. The helpers are included in the current
source bundle; frozen package69 remains a historical smaller artifact.
Neither mode applies the native installation. Paths must be revalidated when
mounts and actual databases are subsequently created under an approved scope.

Historical v1/18-target evidence on30October2026:
../probes/install-preflight-71/evidence/report.json
and its existing-directory, existing-namespace and controlled-exception reports.
This is real read-only IRIS evidence, not a clean installation.

