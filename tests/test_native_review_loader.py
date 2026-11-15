"""Exercise current native Python loader bodies on CPU, without IRIS or models.

Each test uses a fresh interpreter and only namespace-isolated aliases. The
three bodies are extracted from this checkout's ObjectScript sources; no old
snapshot, machine path, package fixture or fixed source hash is required.
"""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys
import types
import unittest

SOURCE = Path(__file__).resolve().parents[1]
CASES = ('current_graph_and_cache', 'prior_graph_regression', 'extra_module',
         'changed_origin', 'missing_clarification', 'wrong_namespace',
         'wrong_root', 'changed_engine_binding')

def need(value, message):
    if not value:
        raise AssertionError(message)

def native_python(section, method, args, *, prior_graph=False):
    path = SOURCE/'src'/'Chronos'/section/'Python.cls'
    lines = path.read_bytes().decode('utf-8').splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if line.startswith('ClassMethod '+method+'(')
               and re.search(r'Language\s*=\s*python\b', line)]
    need(len(headers) == 1, 'Exactly one native Python method is required')
    start = headers[0] + 2
    need(lines[start-1].strip() == '{', 'Unexpected native method boundary')
    end = next(i for i in range(start, len(lines)) if lines[i].rstrip('\r\n') == '}')
    body = ''.join(lines[start:end])
    if prior_graph:
        current = "(agentroot,('__init__','engine','proposal','timeview','extraction','clarification','contract'),'chronos_agent')"
        previous = "(agentroot,('__init__','engine','proposal','timeview','extraction','contract'),'chronos_agent')"
        need(section == 'Review' and body.count(current) == 1, 'Only the reviewed child-list regression may be recreated')
        body = body.replace(current, previous)
    scope = {}
    exec(compile('def call('+args+'):\n'+body, str(path)+':'+method, 'exec'), scope)
    return scope['call']

def package_bytes(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for name in ('chronos_simulation', 'chronos_agent', 'chronos_review')
            for p in (root/name).iterdir() if p.is_file()}

def exercise(case):
    root = (SOURCE/'src').resolve()
    before = package_bytes(root)
    runtime = native_python('Runtime', 'Module', 'root,namespace')
    agent = native_python('Agent', 'Load', 'root,namespace,simulation')
    review = native_python('Review', 'Module', 'root,namespace,agent,simulation',
                           prior_graph=case == 'prior_graph_regression')
    namespace = 'CPU_REVIEW_' + case.upper()
    simulation = runtime(str(root), namespace)
    contract = agent(str(root), namespace, simulation)
    agentroot = contract.rsplit('.', 1)[0]; simroot = simulation.rsplit('.', 1)[0]
    need(agentroot+'.clarification' in sys.modules, 'The real current Agent.Load must load clarification')
    need(not any(name == 'chronos_agent' or name.startswith('chronos_agent.') or
                 name == 'chronos_simulation' or name.startswith('chronos_simulation.')
                 for name in sys.modules), 'Native loaders must not pollute public package aliases')
    expected = None; passed_root = str(root); passed_namespace = namespace
    if case == 'prior_graph_regression':
        expected = 'REVIEW_DEPENDENCY_GRAPH_CHANGED'
    elif case == 'extra_module':
        sys.modules[agentroot+'.unexpected'] = types.ModuleType(agentroot+'.unexpected')
        expected = 'REVIEW_DEPENDENCY_GRAPH_CHANGED'
    elif case == 'changed_origin':
        sys.modules[agentroot+'.clarification'].__file__ = str(root/'wrong-origin.py')
        expected = 'REVIEW_DEPENDENCY_ORIGIN_CHANGED'
    elif case == 'missing_clarification':
        del sys.modules[agentroot+'.clarification']
        expected = 'REVIEW_DEPENDENCY_GRAPH_CHANGED'
    elif case == 'wrong_namespace':
        passed_namespace += '_OTHER'; expected = 'REVIEW_AGENT_BINDING_MISMATCH'
    elif case == 'wrong_root':
        passed_root = str(root/'chronos_review'); expected = 'REVIEW_AGENT_BINDING_MISMATCH'
    elif case == 'changed_engine_binding':
        sys.modules[agentroot+'.engine']._package = simroot+'_OTHER'
        expected = 'REVIEW_ENGINE_BINDING_MISMATCH'
    elif case != 'current_graph_and_cache':
        raise AssertionError('Case outside the fixed test list')
    observed = None; loaded = None
    try:
        loaded = review(passed_root, passed_namespace, contract, simulation)
    except ValueError as error:
        observed = str(error)
    need(observed == expected, 'Expected loader rejection: '+str(expected)+'; observed: '+str(observed))
    if expected is None:
        need(isinstance(loaded, str) and re.fullmatch(r'_chronos_review_[a-f0-9]{64}\.projection', loaded),
             'Review loader must return its private projection alias')
        need(runtime(str(root), namespace) == simulation and agent(str(root), namespace, simulation) == contract and
             review(str(root), namespace, contract, simulation) == loaded, 'Current graph must pass the cache path too')
        projected = sys.modules[loaded]
        need(projected.response_contract_of is sys.modules[contract].response_contract_of and
             projected.validate_explanation is sys.modules[contract].validate_explanation,
             'Projection must retain the actual namespace-owned dependency identities')
    need(package_bytes(root) == before, 'CPU test modified project package files')
    return dict(case=case, status='PASS', rejection=observed)

class NativeReviewLoaderTests(unittest.TestCase):
    def check_case(self, case):
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--loader-case', case],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(case=case, status='PASS', rejection={
            'current_graph_and_cache': None, 'prior_graph_regression': 'REVIEW_DEPENDENCY_GRAPH_CHANGED',
            'extra_module': 'REVIEW_DEPENDENCY_GRAPH_CHANGED', 'changed_origin': 'REVIEW_DEPENDENCY_ORIGIN_CHANGED',
            'missing_clarification': 'REVIEW_DEPENDENCY_GRAPH_CHANGED', 'wrong_namespace': 'REVIEW_AGENT_BINDING_MISMATCH',
            'wrong_root': 'REVIEW_AGENT_BINDING_MISMATCH', 'changed_engine_binding': 'REVIEW_ENGINE_BINDING_MISMATCH'}[case]))

    def test_actual_current_graph_loads_and_reuses_cache(self): self.check_case('current_graph_and_cache')
    def test_prior_missing_child_allowlist_reproduces_real_regression(self): self.check_case('prior_graph_regression')
    def test_extra_module_is_rejected(self): self.check_case('extra_module')
    def test_changed_module_origin_is_rejected(self): self.check_case('changed_origin')
    def test_missing_clarification_is_rejected(self): self.check_case('missing_clarification')
    def test_wrong_namespace_is_rejected(self): self.check_case('wrong_namespace')
    def test_wrong_root_is_rejected(self): self.check_case('wrong_root')
    def test_changed_engine_binding_is_rejected(self): self.check_case('changed_engine_binding')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--loader-case':
        parser = argparse.ArgumentParser(); parser.add_argument('--loader-case', choices=CASES, required=True)
        print(json.dumps(exercise(parser.parse_args().loader_case), sort_keys=True))
    else:
        unittest.main()
