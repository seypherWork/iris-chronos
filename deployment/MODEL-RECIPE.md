# Reproduce the local Qwen candidate

This recipe creates a local alias; `chronos-qwen35:8k-full` is **not** a public
download. It uses the official Qwen3.5 9B Q8_0 model and an 8192-token context.
The GPU profile targets the workstation on which it was tested (16 GiB VRAM).
It does not establish CPU-only or smaller-GPU performance.

## Dedicated setup container

Use a new dedicated model directory. Never point this setup at an
existing shared model cache or overwrite an existing alias. Obtain the official
Ollama image and review the model licence before downloading. Replace the
absolute paths below with your own existing directories; quote the full mounts.
The source directory contains `deployment/Modelfile.qwen35-9b`.

```powershell
$ModelSetup = 'chronos-model-setup-' + [guid]::NewGuid().ToString('N').Substring(0,12)
Write-Output $ModelSetup
docker pull ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d
if ($LASTEXITCODE -ne 0) { throw 'Could not obtain the pinned Ollama image.' }
$SetupStarted = $false
try {
    docker run -d --name "$ModelSetup" --pull never --user 0:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true --restart no --memory 1g --memory-swap 1g --cpus 1 --pids-limit 64 --tmpfs '/tmp:rw,noexec,nosuid,size=268435456,mode=1777' --env HOME=/tmp/chronos --env OLLAMA_HOST=127.0.0.1:11434 --env OLLAMA_MODELS=/models --env OLLAMA_NO_CLOUD=1 --env OLLAMA_NOPRUNE=1 --mount "type=bind,source=ABSOLUTE_MODEL_DIR,target=/models" --mount "type=bind,source=ABSOLUTE_SOURCE_DIR/deployment/Modelfile.qwen35-9b,target=/recipe/Modelfile,readonly" --entrypoint /usr/bin/timeout ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d --signal=KILL 1800 /bin/ollama serve
    if ($LASTEXITCODE -ne 0) { throw "Could not start $ModelSetup. Inspect that exact container before retrying." }
    $SetupStarted = $true
    docker exec "$ModelSetup" /bin/sh -c 'for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do /bin/ollama list >/dev/null 2>&1 && exit 0; sleep 2; done; exit 1'
    if ($LASTEXITCODE -ne 0) { throw 'Ollama did not become ready.' }
    $Version = docker exec "$ModelSetup" ollama --version
    if ($LASTEXITCODE -ne 0 -or ($Version -join ' ') -notmatch '\b0\.40\.13\b') { throw 'Expected Ollama 0.40.13.' }

    docker exec "$ModelSetup" ollama pull qwen3.5:9b-q8_0
    if ($LASTEXITCODE -ne 0) { throw 'The Qwen download failed.' }
    $Base = docker exec "$ModelSetup" ollama list
    if ($LASTEXITCODE -ne 0 -or ($Base -join [Environment]::NewLine) -notmatch '(?m)^qwen3\.5:9b-q8_0\s+a8ee95bc3592\s') { throw 'The downloaded Qwen manifest does not match.' }
    docker exec "$ModelSetup" ollama create chronos-qwen35:8k-full -f /recipe/Modelfile
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the pinned Chronos model alias.' }
    $Aliases = docker exec "$ModelSetup" ollama list
    if ($LASTEXITCODE -ne 0 -or ($Aliases -join [Environment]::NewLine) -notmatch '(?m)^chronos-qwen35:8k-full\s+f565248d3cbe\s') { throw 'The Chronos alias manifest does not match.' }
    $Loaded = @(docker exec "$ModelSetup" ollama ps)
    if ($LASTEXITCODE -ne 0 -or $Loaded.Count -ne 1 -or $Loaded[0] -notmatch '^NAME\s') { throw 'Expected no loaded model.' }
} finally {
    if ($SetupStarted) {
        docker stop "$ModelSetup"
        if ($LASTEXITCODE -ne 0) { throw "Could not stop $ModelSetup. Check that exact container before continuing." }
    }
}
```

Record `$ModelSetup` for this setup attempt. Use that same name when stopping
its container and preserve the existing cache if setup fails.

The readiness command waits at most 30 seconds and makes no inference. Proceed
only if it succeeds and the server version is0.40.13. On failure, stop this setup
container and preserve its cache; do not blindly continue to pull or create. The
image reference above was read back from the tested image's `RepoDigests`; it is
not inferred solely from a local image ID.

The setup container has outbound network access for the official download, no
published ports, no GPU and a 30-minute maximum lifetime. It writes only the
chosen model directory. Its root user is internal to that restricted container;
the normal inference service remains user51773. Creating the alias does not run
inference: `ollama ps` must show no loaded model. Stop the setup container even
if a command fails; preserve its files for diagnosis rather than replacing them.
Do not rerun initialization against a partial cache without inspecting it.

The base manifest recorded for this recipe is
`a8ee95bc3592ebaa624014ca8b429d25e0ef5f45030dc35786da7ff7e9e1b60a`.
The alias created by official Ollama 0.40.13 has manifest digest
`f565248d3cbe09b10fe6702db3bd0a681711fb1170fbeea754cc077a8cf2b0ff`.
The list output abbreviates this digest; the readiness helper must validate the
full digest during the final runtime check. A changed tag or name alone is not
evidence that the same weights and settings were obtained.

Configure `CHRONOS_MODELS` to this prepared directory. Compose mounts it
read-only. Use a separate new `CHRONOS_MODEL_HOME` for writable runtime files. Continue with the [canonical jury route](JURY-ROUTE.md)
for Compose, both profiles and the neutral warmup. Do not start
a timed business case before the warmup succeeds.

## Evidence boundary

The recipe was executed against an already obtained, hash-verified official base
in an isolated private cache, without inference. Its weights, projector,
template, licence, config and parsed parameters match the earlier laboratory
alias. Official creation changes serialization, provenance labels and the runner
metadata, so its manifest digest differs from the historical
`59819759534ba21294cbd1b42eb4bf92f2fb9da6521560ba9975871e4f31c814`.
Do not relabel old inference evidence as a test of the new digest.

The reproduced alias completed real neutral readiness with an 8192-token context
and all 33 layers on GPU. Later native E1/C2v2 browser journeys and the one-round
known-corpus E1 comparison are recorded in [EVIDENCE.md](EVIDENCE.md); they are
separate from creating this alias. The [final native rehearsal](EVIDENCE.md#final-native-rehearsal)
used the prepared cache in read-only mode. Downloading the base model from
scratch on independent hardware was outside that rehearsal.

Sources: [official model](https://ollama.com/library/qwen3.5:9b-q8_0),
[Modelfile reference](https://docs.ollama.com/modelfile).


