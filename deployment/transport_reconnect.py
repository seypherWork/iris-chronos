"""Reconnect existing Chronos transports after an engine container restart.

No container creation, native lifecycle request, allowance preparation or model
inference. Only explicitly named, running sidecars can be restarted. A partial
or uncertain outcome is retained; no restart is automatically repeated.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

MAX_JSON = 256 * 1024
ROLES = ('model', 'guard', 'conversation-guard')
FIELDS = ('{"id":{{json .Id}},"image":{{json .Image}},'
          '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
          '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
          '"entrypoint":{{json .Config.Entrypoint}},"command":{{json .Config.Cmd}},'
          '"user":{{json .Config.User}},"state":{{json .State}},'
          '"host":{{json .HostConfig}},"mounts":{{json .Mounts}}}')


def need(value, code):
    if not value:
        raise ValueError(code)


def cid(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


class Docker:
    def __init__(self, executable, *, run=subprocess.run):
        path = Path(executable)
        need(path.is_absolute() and path.name.lower() in {'docker', 'docker.exe'}, 'LOCAL_DOCKER_REQUIRED')
        self.executable, self.run = str(path), run
        self.host = 'npipe:////./pipe/dockerDesktopLinuxEngine' if os.name == 'nt' else 'unix:///var/run/docker.sock'

    def call(self, args, *, timeout=30):
        env = dict(os.environ)
        for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            env.pop(name, None)
        try:
            value = self.run([self.executable, '--host', self.host, *args], capture_output=True,
                             text=True, encoding='utf-8', env=env, check=False, timeout=timeout)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ValueError('DOCKER_OUTCOME_UNCERTAIN_INSPECT_SAME_CONTAINERS') from None
        need(value.returncode == 0 and len(value.stdout.encode('utf-8')) <= MAX_JSON,
             'DOCKER_COMMAND_FAILED_STATE_PRESERVED')
        return value.stdout.strip()

    def inspect(self, ident):
        need(cid(ident), 'FULL_CONTAINER_ID_REQUIRED')
        return json.loads(self.call(['inspect', '--type', 'container', '--format', FIELDS, ident]))

    def namespace(self, ident, role):
        need(cid(ident) and role in ('iris', *ROLES), 'INVALID_NAMESPACE_TARGET')
        # No caller text is interpreted by a shell; both executables only read /proc.
        command = (['/usr/bin/readlink', '/proc/self/ns/net'] if role == 'model' else
                   ['/usr/bin/python3', '-B', '-c', 'import os; print(os.readlink("/proc/self/ns/net"))'])
        value = self.call(['exec', ident, *command])
        need(re.fullmatch(r'net:\[[0-9]+\]', value) is not None, 'NETWORK_NAMESPACE_UNVERIFIED')
        return value

    def endpoint(self, engine, role):
        need(cid(engine) and role in ROLES, 'INVALID_ENDPOINT_TARGET')
        port = {'model': 11434, 'guard': 11512, 'conversation-guard': 11514}[role]
        path = '/api/version' if role == 'model' else '/'
        # http.client follows neither redirects nor environment proxy settings.
        code = ('import json,http.client\n'
                'try:\n'
                f' c=http.client.HTTPConnection("127.0.0.1",{port},timeout=2); c.request("GET","{path}"); r=c.getresponse(); '
                'print(json.dumps({"status":r.status,"body":json.loads(r.read(2049))}))\n'
                'except Exception:\n print(json.dumps({"status":0,"body":{}}))')
        value = json.loads(self.call(['exec', engine, '/usr/bin/python3', '-B', '-c', code]))
        if role == 'model':
            return value.get('status') == 200 and type(value.get('body', {}).get('version')) is str
        return value == {'status': 404, 'body': {'error': {'code': 'ROUTE_NOT_ALLOWED'}}}

    def reserve(self, engine, generation, services):
        """One durable, atomic reconnect attempt per actual engine generation.

        Kept inside the existing owned durable-data bind mount, so separate processes
        and host users share the fence. A timeout never permits clearing it.
        """
        fence = sha256((engine + ':' + generation).encode('utf-8')).hexdigest()
        record = json.dumps({'engine_id': engine, 'engine_started_at': generation,
                             'sidecar_ids': sorted(services)}, sort_keys=True)
        code = ('import os,json,sys\n'
                'root=os.open("/durable",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)\n'
                'try:\n'
                ' try: os.mkdir("transport-reconnect",mode=0o700,dir_fd=root)\n'
                ' except FileExistsError: pass\n'
                ' child=os.open("transport-reconnect",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)\n'
                ' try:\n'
                '  try: fd=os.open(sys.argv[1]+".json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=child)\n'
                '  except FileExistsError: print(json.dumps({"claimed":False}))\n'
                '  else:\n'
                '   with os.fdopen(fd,"w") as f: f.write(sys.argv[2]);f.flush();os.fsync(f.fileno())\n'
                '   os.fsync(child);print(json.dumps({"claimed":True}))\n'
                ' finally: os.close(child)\n'
                'finally: os.close(root)')
        value = json.loads(self.call(['exec', '--user', '51773:51773', engine,
                                     '/usr/bin/python3', '-B', '-c', code, fence, record]))
        need(value == {'claimed': True}, 'RECONNECT_GENERATION_ALREADY_RESERVED_INSPECT_SAME_ATTEMPT')
        return fence


def mounts(value):
    result = {item['Destination']: item for item in value['mounts']}
    need(len(result) == len(value['mounts']) and all(item['Type'] == 'bind' for item in result.values()),
         'BIND_MOUNTS_REQUIRED')
    return result


def owned(value, ident, project, role, *, engine=None):
    need(value['id'] == ident and value['project'] == project and value['service'] == role,
         'CONTAINER_OWNERSHIP_CHANGED')
    state, host = value['state'], value['host']
    need(state['Running'] is True and state['OOMKilled'] is False, 'PREVIOUSLY_RUNNING_SERVICE_REQUIRED')
    need(not host['Privileged'] and host['RestartPolicy']['Name'] == 'no', 'SERVICE_AUTHORITY_CHANGED')
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', value['image']) is not None, 'PINNED_IMAGE_REQUIRED')
    if role == 'iris':
        need(host['Memory'] == 4 * 2**30 and 0 < host['NanoCpus'] <= 2 * 10**9,
             'ENGINE_RESOURCE_SCOPE_CHANGED')
        need(host['NetworkMode'] == project + '_default', 'ENGINE_NETWORK_SCOPE_CHANGED')
        bound = mounts(value)
        need('/durable' in bound and bound['/durable']['RW'] is True, 'OWNED_DURABLE_CONTROL_MOUNT_REQUIRED')
        return
    need(engine is not None and host['NetworkMode'] == 'container:' + engine['id']
         and not host.get('PortBindings') and not host['PublishAllPorts']
         and value['user'] == '51773:51773' and host['CapDrop'] == ['ALL'] and not host.get('CapAdd')
         and any(v in host['SecurityOpt'] for v in ('no-new-privileges', 'no-new-privileges:true')),
         'SIDECAR_AUTHORITY_CHANGED')
    need(0 < host['Memory'] <= (8 * 2**30 if role == 'model' else 256 * 2**20)
         and 0 < host['NanoCpus'] <= (4 * 10**9 if role == 'model' else 5 * 10**8),
         'SIDECAR_RESOURCE_SCOPE_CHANGED')
    bound = mounts(value)
    if role == 'model':
        need(set(bound) == {'/models', '/model-home'} and not bound['/models']['RW'], 'MODEL_MOUNTS_CHANGED')
    else:
        native = mounts(engine)
        need(value['image'] == engine['image'] and host['ReadonlyRootfs'] and not host.get('DeviceRequests')
             and set(bound) in ({'/opt/chronos/src', '/opt/chronos/runtime'},
                                {'/opt/chronos/src', '/opt/chronos/deployment', '/opt/chronos/runtime'}),
             'GUARD_MOUNTS_CHANGED')
        for target in set(bound) - {'/opt/chronos/runtime'}:
            need(target in native and bound[target]['Source'] == native[target]['Source'] and not bound[target]['RW'],
                 'GUARD_SOURCE_CHANGED')
        runtime = '/opt/chronos/runtime' if role == 'guard' else '/opt/chronos/conversation-runtime'
        need(runtime in native and bound['/opt/chronos/runtime']['Source'] == native[runtime]['Source']
             and bound['/opt/chronos/runtime']['RW'],
             'GUARD_STATE_CHANGED')


def immutable(value):
    return {key: value[key] for key in ('id', 'image', 'project', 'service', 'user', 'entrypoint', 'command', 'host', 'mounts')}


def reconnect(docker, engine_id, deployment_id, sidecar_ids, output, *, authorize_engine_id,
              monotonic=time.monotonic, sleep=time.sleep):
    need(cid(engine_id) and type(deployment_id) is str and re.fullmatch('[a-f0-9]{32}', deployment_id), 'INVALID_BINDING')
    need(authorize_engine_id == engine_id, 'EXPLICIT_ENGINE_BOUND_AUTHORIZATION_REQUIRED')
    need(type(sidecar_ids) is list and len(sidecar_ids) in (2, 3) and all(cid(v) for v in sidecar_ids)
         and len(set(sidecar_ids + [engine_id])) == len(sidecar_ids) + 1, 'EXACT_SIDECAR_SET_REQUIRED')
    output = Path(output)
    need(output.is_absolute() and not output.exists() and not output.is_symlink(), 'NEW_ABSOLUTE_EVIDENCE_DIRECTORY_REQUIRED')
    for parent in (output.parent, *output.parent.parents):
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
             and not getattr(info, 'st_file_attributes', 0) & 0x400, 'PLAIN_EVIDENCE_PARENT_REQUIRED')
    # Verify all containers before reserving or restarting any of them.
    project = 'chronos-jury-' + deployment_id[:12]
    engine = docker.inspect(engine_id)
    owned(engine, engine_id, project, 'iris')
    entries = [docker.inspect(v) for v in sidecar_ids]
    roles = [v['service'] for v in entries]
    need(set(roles) == ({'guard', 'conversation-guard'} if len(entries) == 2 else set(ROLES))
         and len(set(roles)) == len(roles), 'EXACT_SIDECAR_SET_REQUIRED')
    for value in entries:
        owned(value, value['id'], project, value['service'], engine=engine)
    generation = engine['state']['StartedAt']
    namespace = docker.namespace(engine_id, 'iris')
    before = {v['service']: docker.namespace(v['id'], v['service']) for v in entries}
    expected_starts = {v['service']: v['state']['StartedAt'] for v in entries}
    output.mkdir(exist_ok=False)
    report = {'schema': 'chronos.transport-reconnect.v1', 'engine_id': engine_id,
              'deployment_id': deployment_id, 'engine_started_at': generation,
              'captured_at': datetime.now(timezone.utc).isoformat(), 'namespace': namespace,
              'status': 'REQUESTED', 'accounts_changed': 0, 'inference_requested': False,
              'native_resume_requested': False, 'ready': False, 'services': []}
    def save(name, value):
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
    def current_engine():
        now = docker.inspect(engine_id)
        owned(now, engine_id, project, 'iris')
        need(immutable(now) == immutable(engine) and now['state']['StartedAt'] == generation
             and docker.namespace(engine_id, 'iris') == namespace, 'ENGINE_GENERATION_CHANGED')
    save('intent.json', {**report, 'sidecar_ids': sidecar_ids, 'before_namespaces': before})
    try:
        if any(v != namespace for v in before.values()):
            current_engine()
            report['generation_fence'] = docker.reserve(engine_id, generation, sidecar_ids)
        for value in sorted(entries, key=lambda v: ROLES.index(v['service'])):
            role, ident = value['service'], value['id']
            current_engine()
            now = docker.inspect(ident)
            owned(now, ident, project, role, engine=engine)
            need(immutable(now) == immutable(value) and now['state']['StartedAt'] == value['state']['StartedAt'],
                 'SIDECAR_CHANGED_BEFORE_RECONNECT')
            observed = docker.namespace(ident, role)
            row = {'service': role, 'container_id': ident, 'previous_namespace': observed, 'restart_requested': False}
            report['services'].append(row)
            if observed != namespace:
                save(role + '-restart-intent.json', {'container_id': ident, 'engine_id': engine_id,
                     'engine_started_at': generation, 'previous_started_at': now['state']['StartedAt']})
                row['restart_requested'] = True
                docker.call(['restart', '--time=10', ident], timeout=35)
                changed = docker.inspect(ident)
                owned(changed, ident, project, role, engine=engine)
                need(immutable(changed) == immutable(value) and changed['state']['StartedAt'] != now['state']['StartedAt'],
                     'SIDECAR_RESTART_UNVERIFIED')
                expected_starts[role] = changed['state']['StartedAt']
            current_engine()
            need(docker.namespace(ident, role) == namespace, 'SIDECAR_NAMESPACE_NOT_RECONNECTED')
            until = monotonic() + 15
            while not docker.endpoint(engine_id, role):
                need(monotonic() < until, 'TRANSPORT_ENDPOINT_UNVERIFIED')
                current_engine()
                sleep(.5)
            row['same_namespace'] = True
            row['endpoint_readback'] = True
            row['started_at'] = expected_starts[role]
        current_engine()
        for value in entries:
            now = docker.inspect(value['id'])
            owned(now, value['id'], project, value['service'], engine=engine)
            need(immutable(now) == immutable(value) and docker.namespace(value['id'], value['service']) == namespace
                 and now['state']['StartedAt'] == expected_starts[value['service']]
                 and docker.endpoint(engine_id, value['service']), 'FINAL_TRANSPORT_READBACK_CHANGED')
        current_engine()
        report['status'] = 'TRANSPORT_CONNECTIVITY_VERIFIED_NOT_MODEL_INFERENCE'
        return report
    except Exception as error:
        report['status'] = 'PARTIAL_OR_UNCERTAIN_INSPECT_SAME_CONTAINERS'
        report['diagnostic'] = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'RECONNECT_OUTCOME_UNVERIFIED'
        raise
    finally:
        save('result.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('docker', 'engine-id', 'deployment-id', 'output', 'authorize-engine-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--sidecar-id', required=True, action='append')
    args = parser.parse_args(argv)
    try:
        result = reconnect(Docker(args.docker), args.engine_id, args.deployment_id, args.sidecar_id,
                           args.output, authorize_engine_id=args.authorize_engine_id)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'REJECTED_OR_PARTIAL_INSPECT_RETAINED_EVIDENCE', 'ready': False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
