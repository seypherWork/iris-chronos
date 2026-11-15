"""Synthetic boundary tests; these do not run IRIS or Docker."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('transport_reconnect', Path(__file__).resolve().parents[1] / 'deployment/transport_reconnect.py')
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)
ENGINE = 'a' * 64
DEPLOYMENT = 'b' * 32
GUARD = 'c' * 64
CHAT = 'd' * 64

def mount(target, source, rw):
    return {'Type': 'bind', 'Destination': target, 'Source': source, 'RW': rw}

def entry(ident, role):
    engine = role == 'iris'
    return {'id': ident, 'image': 'sha256:' + 'e' * 64,
            'project': 'chronos-jury-' + DEPLOYMENT[:12], 'service': role,
            'user': '51773:51773',
            'entrypoint': ['/usr/bin/python3'], 'command': ['SYNTHETIC'],
            'state': {'Running': True, 'OOMKilled': False, 'StartedAt': 'original'},
            'host': {'Privileged': False, 'RestartPolicy': {'Name': 'no'},
                     'Memory': 4 * 2**30 if engine else 256 * 2**20,
                     'NanoCpus': 2 * 10**9 if engine else 5 * 10**8,
                     'NetworkMode': 'chronos-jury-' + DEPLOYMENT[:12] + '_default' if engine else 'container:' + ENGINE,
                     'PortBindings': {}, 'PublishAllPorts': False, 'CapDrop': ['ALL'],
                     'CapAdd': None, 'SecurityOpt': ['no-new-privileges'],
                     'ReadonlyRootfs': True, 'DeviceRequests': []},
            'mounts': [mount('/opt/chronos/src', '/private/source', False),
                       mount('/opt/chronos/runtime', '/private/e1', True)] +
                      ([mount('/opt/chronos/conversation-runtime', '/private/c2', True),
                        mount('/durable', '/private/durable', True)] if engine else [])}

class FakeDocker:
    def __init__(self):
        self.entries = {ENGINE: entry(ENGINE, 'iris'), GUARD: entry(GUARD, 'guard'), CHAT: entry(CHAT, 'conversation-guard')}
        self.entries[CHAT]['mounts'][1]['Source'] = '/private/c2'
        self.namespaces = {ENGINE: 'net:[2]', GUARD: 'net:[1]', CHAT: 'net:[1]'}
        self.calls = []
        self.reserved = False
    def reserve(self, engine, generation, services):
        if self.reserved: raise ValueError('RECONNECT_GENERATION_ALREADY_RESERVED_INSPECT_SAME_ATTEMPT')
        self.reserved = True
        return 'f' * 64
    def inspect(self, ident):
        return deepcopy(self.entries[ident])
    def namespace(self, ident, role):
        return self.namespaces[ident]
    def endpoint(self, ident, role):
        return True
    def call(self, args, **kwargs):
        self.calls.append(args)
        assert args[:2] == ['restart', '--time=10']
        ident = args[-1]
        self.namespaces[ident] = self.namespaces[ENGINE]
        self.entries[ident]['state']['StartedAt'] = 'restarted'
        return ident

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ctr-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.docker = FakeDocker()
    def run_reconnect(self, **kwargs):
        inputs = dict(authorize_engine_id=ENGINE)
        inputs.update(kwargs)
        return r.reconnect(self.docker, ENGINE, DEPLOYMENT, [GUARD, CHAT], self.folder / 'proof', **inputs)
    def test_reconnects_only_stale_owned_sidecars(self):
        result = self.run_reconnect()
        self.assertEqual([x[-1] for x in self.docker.calls], [GUARD, CHAT])
        self.assertFalse(result['ready'])
        self.assertFalse(result['inference_requested'])
        self.assertFalse(result['native_resume_requested'])
    def test_second_explicit_observation_has_no_additional_restarts(self):
        self.run_reconnect()
        self.docker.calls.clear()
        r.reconnect(self.docker, ENGINE, DEPLOYMENT, [GUARD, CHAT], self.folder / 'second', authorize_engine_id=ENGINE)
        self.assertEqual(self.docker.calls, [])
    def test_matching_network_mode_is_not_namespace_proof(self):
        self.assertEqual(self.docker.entries[GUARD]['host']['NetworkMode'], 'container:' + ENGINE)
        self.run_reconnect()
        self.assertEqual(len(self.docker.calls), 2)
    def test_authorization_precedes_any_docker_call(self):
        with self.assertRaisesRegex(ValueError, 'AUTHORIZATION'):
            self.run_reconnect(authorize_engine_id='f' * 64)
        self.assertEqual(self.docker.calls, [])
        self.assertFalse((self.folder / 'proof').exists())
    def test_foreign_project_stopped_service_and_bad_mounts_reject_before_restart(self):
        for mutate in (lambda v: v.update(project='other'),
                       lambda v: v['state'].update(Running=False),
                       lambda v: v['mounts'][0].update(Source='/another/source'),
                       lambda v: v['host'].update(Privileged=True),
                       lambda v: v['host'].update(NetworkMode='host'),
                       lambda v: v['host'].update(Memory=2 * 2**30)):
            with self.subTest(mutate=mutate):
                self.docker = FakeDocker()
                mutate(self.docker.entries[CHAT])
                with self.assertRaises(ValueError): self.run_reconnect()
                self.assertEqual(self.docker.calls, [])
    def test_uncertain_restart_is_not_repeated_and_retains_result(self):
        def uncertain(args, **kwargs):
            self.docker.calls.append(args)
            raise ValueError('DOCKER_OUTCOME_UNCERTAIN')
        self.docker.call = uncertain
        with self.assertRaisesRegex(ValueError, 'UNCERTAIN'): self.run_reconnect()
        self.assertEqual(len(self.docker.calls), 1)
        saved = json.loads((self.folder / 'proof/result.json').read_text())
        self.assertEqual(saved['status'], 'PARTIAL_OR_UNCERTAIN_INSPECT_SAME_CONTAINERS')
    def test_engine_generation_change_prevents_restart(self):
        inspect = self.docker.inspect
        count = 0
        def changes(ident):
            nonlocal count
            value = inspect(ident)
            if ident == ENGINE:
                count += 1
                if count > 1: value['state']['StartedAt'] = 'changed'
            return value
        self.docker.inspect = changes
        with self.assertRaisesRegex(ValueError, 'GENERATION'): self.run_reconnect()
        self.assertEqual(self.docker.calls, [])
    def test_failed_endpoint_does_not_repeat_restart(self):
        self.docker.endpoint = lambda *args: False
        ticks = iter([0, 16])
        with self.assertRaisesRegex(ValueError, 'ENDPOINT'):
            self.run_reconnect(monotonic=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(len(self.docker.calls), 1)
    def test_second_concurrent_reservation_never_restarts_any_service(self):
        self.docker.reserved = True
        with self.assertRaisesRegex(ValueError, 'ALREADY_RESERVED'): self.run_reconnect()
        self.assertEqual(self.docker.calls, [])
    def test_late_restart_of_an_earlier_guard_prevents_final_verification(self):
        endpoint = self.docker.endpoint
        def later_change(engine, role):
            if role == 'conversation-guard':
                self.docker.entries[GUARD]['state']['StartedAt'] = 'external-restart'
            return endpoint(engine, role)
        self.docker.endpoint = later_change
        with self.assertRaisesRegex(ValueError, 'FINAL_TRANSPORT'): self.run_reconnect()
        saved = json.loads((self.folder / 'proof/result.json').read_text())
        self.assertNotEqual(saved['status'], 'TRANSPORT_CONNECTIVITY_VERIFIED_NOT_MODEL_INFERENCE')
    def test_duplicate_cids_or_missing_guard_are_rejected(self):
        with self.assertRaises(ValueError):
            r.reconnect(self.docker, ENGINE, DEPLOYMENT, [GUARD, GUARD], self.folder / 'proof', authorize_engine_id=ENGINE)
        self.docker.entries[CHAT]['service'] = 'model'
        with self.assertRaises(ValueError): self.run_reconnect()
        self.assertEqual(self.docker.calls, [])
    def test_existing_evidence_never_replaced(self):
        (self.folder / 'proof').mkdir()
        (self.folder / 'proof/preserve.txt').write_text('preserve')
        with self.assertRaises(ValueError): self.run_reconnect()
        self.assertEqual((self.folder / 'proof/preserve.txt').read_text(), 'preserve')
        self.assertEqual(self.docker.calls, [])
    def test_docker_wrapper_keeps_local_endpoint_and_argument_boundaries(self):
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, 'net:[123]\n', '')
        wrapper = r.Docker(Path(__file__).parent / 'docker.exe', run=run)
        self.assertEqual(wrapper.namespace(ENGINE, 'iris'), 'net:[123]')
        args, kwargs = calls[0]
        self.assertEqual(args[-1], 'import os; print(os.readlink("/proc/self/ns/net"))')
        self.assertNotIn('shell', kwargs)

if __name__ == '__main__':
    unittest.main(verbosity=2)
