"""Bounded local workers for trusted source; no model agents or background daemon.

Isolation is separate processes, snapshots and clean environments. Application
audit checks are defense in depth, NOT a sandbox for malicious Python code.
Never submit untrusted executable code; external/privileged work is escalated.
"""
import argparse
import ast
import contextlib
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import unittest

from discovery_review import digest
from learning_cycle import (MAX_BYTES, demo_inputs, private_directory, read_json,
                            run_cycle, prepare_single_review, run_single_review)
from learning_pipeline import extract_envelope
from review_store import atomic_json_create

ROLES = {'coding', 'research', 'testing', 'intelligence'}
PERMISSIONS = {
    'repository_write': False, 'canonical_write': False, 'credential_access': False,
    'network': 'denied by application audit guard; not an OS security boundary',
    'execution': 'fixed trusted handlers; trusted Python tests only',
    'isolation': 'process and snapshot; not a hostile-code sandbox',
}


def validate_task(task):
    required = {'id', 'role', 'action', 'payload'}
    if not isinstance(task, dict) or not required <= set(task) <= required | {'depends_on'}:
        raise ValueError('Task requires id, role, action, payload and optional depends_on only')
    if not isinstance(task['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', task['id']):
        raise ValueError('Invalid bounded task ID')
    if not isinstance(task['role'], str) or task['role'] not in ROLES or not isinstance(task['payload'], dict):
        raise ValueError('Unknown role or payload')
    dependencies = task.get('depends_on', [])
    if (not isinstance(dependencies, list) or len(dependencies) > 8
            or not all(isinstance(d, str) for d in dependencies)
            or len(set(dependencies)) != len(dependencies)):
        raise ValueError('Dependencies must be a bounded list of unique task IDs')
    actions = {'coding': ('propose_edit',), 'research': ('extract', 'prepare_review'),
               'testing': ('unittest',), 'intelligence': ('cycle', 'review_single')}
    return task['action'] in actions[task['role']]


def guard(root):
    """Constrain trusted built-ins; do not rely on Python hooks for hostile code."""
    root = Path(root).resolve()

    def inside(path):
        return isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).resolve().is_relative_to(root)

    def audit(event, args):
        if event.startswith('socket.') or event in ('os.system', 'os.exec', 'os.posix_spawn', 'ctypes.dlopen'):
            raise PermissionError('Worker capability denied')
        if event == 'subprocess.Popen':
            # Recovered growth regression tests invoke only this fixed CLI.
            command = args[1]
            allowed = (isinstance(command, (list, tuple)) and len(command) >= 3
                       and Path(command[0]).resolve() == Path(sys.executable).resolve()
                       and Path(command[1]).resolve() == root / 'src' / 'growth_links.py'
                       and command[2] in ('link', 'list'))
            if not allowed:
                raise PermissionError('Subprocess outside fixed worker capabilities')
        if event == 'open':
            path, _, flags = args
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and not isinstance(path, int) and not inside(path):
                raise PermissionError('Write outside task workspace')
            if not isinstance(path, int) and not inside(path):
                resolved = Path(os.fsdecode(path)).resolve()
                # Runtime libraries only, never arbitrary host files or credentials.
                if not any(resolved.is_relative_to(Path(p).resolve()) for p in
                           (sys.base_prefix, '/usr/lib', '/usr/local/lib')):
                    raise PermissionError('Read outside task workspace or Python runtime')
        if event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown', 'os.truncate', 'os.utime'):
            if not inside(args[0]):
                raise PermissionError('Mutation outside task workspace')
        if event in ('os.rename', 'os.link', 'os.symlink'):
            if not inside(args[0]) or not inside(args[1]):
                raise PermissionError('Mutation outside task workspace')
    sys.addaudithook(audit)


def execute(task, root):
    """Fixed operations; source bodies are never dispatched as instructions."""
    payload = task['payload']
    role = task['role']
    if role == 'coding':
        if set(payload) != {'path', 'expected_sha256', 'before', 'after'}:
            raise ValueError('Coding worker needs one explicit edit and expected content hash')
        name = payload['path']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]+\.py', name):
            raise ValueError('One top-level Python source file required')
        path = root / 'src' / name
        original = path.read_text()
        if hashlib.sha256(path.read_bytes()).hexdigest() != payload['expected_sha256']:
            raise ValueError('Stale coding task; source hash mismatch')
        before, after = payload['before'], payload['after']
        if not isinstance(before, str) or not before or not isinstance(after, str) or original.count(before) != 1:
            raise ValueError('Edit must match exactly once')
        proposed = original.replace(before, after, 1)
        ast.parse(proposed)
        patch = ''.join(difflib.unified_diff(original.splitlines(True), proposed.splitlines(True),
                                            fromfile='a/' + name, tofile='b/' + name))
        (root / 'proposal.patch').write_text(patch)
        (root / 'proposed.py').write_text(proposed)
        return {'proposal': 'proposal.patch', 'applied_to_repository': False,
                'patch_sha256': hashlib.sha256(patch.encode()).hexdigest(),
                'target': name, 'original_sha256': payload['expected_sha256'],
                'proposal_file': 'proposed.py', 'proposed_sha256': hashlib.sha256(proposed.encode()).hexdigest()}
    if role == 'research':
        if task['action'] == 'prepare_review':
            if set(payload) != {'plan', 'selected'}:
                raise ValueError('Research review requires explicit plan and selected evidence')
            envelope = prepare_single_review(payload['plan'], payload['selected'])
            handoff = {'schema': 'diamond.review-handoff/1', 'plan': payload['plan'], 'selected': payload['selected']}
            atomic_json_create(root / 'handoff.json', handoff)
            return {'handoff_file': 'handoff.json', 'handoff_hash': digest(handoff),
                    'input_kind': payload['plan']['input_kind'],
                    'reviewed_spans': len(envelope['analysis']['ideas']),
                    'evidence_state': 'UNRESOLVED', 'canonical': False}
        if (set(payload) != {'selected', 'projects', 'reviewed_at', 'input_kind'}
                or payload['input_kind'] not in ('synthetic', 'real')
                or not 1 <= len(payload['selected']) <= 8):
            raise ValueError('Bounded selected evidence required')
        packets = []
        for selected in payload['selected']:
            envelope = extract_envelope(selected['source'], selected['approval'],
                                        'Bounded research worker', payload['reviewed_at'], payload['projects'])
            from discovery_review import prepare
            packet, _ = prepare(**envelope)
            packets.append({'packet_hash': packet['packet_hash'],
                            'assertions': len(packet['analysis']['ideas']), 'evidence_state': 'UNRESOLVED'})
        return {'evidence': packets, 'input_kind': payload['input_kind'],
                'input_provenance': 'operator-declared; not independently verified',
                'independent_verification_established': False}
    if role == 'intelligence':
        if set(payload) != {'plan', 'selected'}:
            raise ValueError('Intelligence requires explicit cycle plan and selected inputs')
        if task['action'] == 'review_single':
            return run_single_review(payload['plan'], payload['selected'], root / 'reviews')
        return run_cycle(payload['plan'], payload['selected'], root / 'reviews')
    if set(payload) != {'pattern'} or not re.fullmatch(r'test_[A-Za-z0-9_*]+\.py', payload['pattern']):
        raise ValueError('Testing requires a bounded unittest discovery pattern')
    suite = unittest.defaultTestLoader.discover(str(root / 'src'), pattern=payload['pattern'])
    with (root / 'test-output.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
    return {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped),
            'successful': result.wasSuccessful() and result.testsRun > len(result.skipped), 'output': 'test-output.log'}


def worker(task_file):
    root = Path.cwd().resolve()
    task = read_json(task_file)
    if not validate_task(task):
        raise ValueError('Unsupported worker action')
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    tempfile.tempdir = str(root / 'tmp')
    guard(root)
    result = execute(task, root)
    atomic_json_create(root / 'result.json', {'role': task['role'], 'result': result,
                                             'canonical': False, 'review_required': True})


def coordinate(tasks, source, destination, timeout=30):
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
        raise ValueError('One to eight tasks required')
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError('Timeout must be 1..60 seconds')
    preceding = set()
    for task in tasks:
        validate_task(task)
        if not set(task.get('depends_on', [])) <= preceding:
            raise ValueError('Dependencies must reference preceding tasks; cycles and forward references rejected')
        preceding.add(task['id'])
        if len(json.dumps(task).encode()) > MAX_BYTES:
            raise ValueError('Task exceeds bounded input budget')
    if len({t['id'] for t in tasks}) != len(tasks):
        raise ValueError('Task IDs must be unique')
    source = Path(source).resolve()
    # Copy only bounded regular Python source, never Git state or credential files.
    files = sorted(source.glob('*.py'))
    if not files or len(files) > 64 or any(p.is_symlink() or p.stat().st_size > MAX_BYTES for p in files):
        raise ValueError('Bounded regular trusted source snapshot required')
    snapshot = {p.name: p.read_bytes() for p in files}
    if sum(map(len, snapshot.values())) > 8 * 1024**2:
        raise ValueError('Source snapshot exceeds eight-megabyte budget')
    fingerprint = digest({name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()})
    destination = private_directory(destination)
    run_root = Path(tempfile.mkdtemp(prefix='workers-', dir=destination))
    reports = []
    for task in tasks:
        root = run_root / task['id']
        root.mkdir(mode=0o700)
        (root / 'src').mkdir(mode=0o700)
        (root / 'tmp').mkdir(mode=0o700)
        for name, data in snapshot.items():
            (root / 'src' / name).write_bytes(data)
        report = {'task_id': task['id'], 'role': task['role'], 'permissions': PERMISSIONS,
                  'source_fingerprint': fingerprint, 'canonical': False, 'review_required': True,
                  'worker_started': False}
        failed_dependencies = [d for d in task.get('depends_on', [])
                               if next(r for r in reports if r['task_id'] == d)['state'] != 'completed']
        if failed_dependencies:
            report.update(state='blocked_dependency', dependencies=failed_dependencies,
                          escalation='Resolve failed prerequisite with the responsible specialist before retrying')
        elif not validate_task(task):
            report.update(state='needs_specialist', escalation='Unsupported capability; supervisor must assign a specialist explicitly')
        else:
            # Transfer only specific, hash-checked artifacts from successful prerequisites.
            try:
                task = resolve_handoff(task, reports, run_root, root, snapshot)
                if task['role'] == 'testing' and task.get('_tested_proposal'):
                    report['tested_proposal'] = task.pop('_tested_proposal')
                atomic_json_create(root / 'task.json', task)
            except (ValueError, KeyError, OSError, TypeError):
                report.update(state='failed', escalation='Invalid or stale prerequisite artifact; specialist review required')
                atomic_json_create(root / 'report.json', report)
                reports.append(report)
                continue
            # Explicitly no inherited environment, credentials, proxy or user-site hooks.
            env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
                   'TMPDIR': str(root / 'tmp'), 'LANG': 'C.UTF-8', 'DIAMOND_WORKER': '1'}
            bootstrap = ('import sys; sys.dont_write_bytecode=True; '
                         'sys.path.insert(0,"src"); '
                         'from agent_coordinator import worker; worker("task.json")')
            with (root / 'worker-output.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-I', '-S', '-c', bootstrap],
                                           cwd=root, env=env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, start_new_session=True)
                report['worker_started'] = True
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    report.update(state='timed_out', escalation='Specialist review required; task exceeded time budget')
                else:
                    if process.returncode != 0 or not (root / 'result.json').is_file():
                        report.update(state='failed', escalation='Inspect private worker log; no automatic privilege expansion')
                    else:
                        result = read_json(root / 'result.json')
                        report.update(state='completed', result=result['result'])
                        if task['role'] == 'testing' and not result['result']['successful']:
                            report.update(state='failed', escalation='Testing specialist required')
        atomic_json_create(root / 'report.json', report)
        reports.append(report)
    summary = {'execution': 'fixed local worker processes; no model agents',
               'workers_started': sum(r['worker_started'] for r in reports),
               'run_directory': str(run_root), 'tasks': reports, 'canonical': False}
    atomic_json_create(run_root / 'summary.json', summary)
    return summary


def resolve_handoff(task, reports, run_root, root, snapshot):
    """Fixed handoff types only; no worker-controlled file paths or commands."""
    task = json.loads(json.dumps(task))
    payload = task['payload']

    def prior(task_id, role):
        if task_id not in task.get('depends_on', []):
            raise ValueError('Artifact transfer requires an explicit prerequisite')
        result = next((r for r in reports if r['task_id'] == task_id), None)
        if not result or result['state'] != 'completed' or result['role'] != role:
            raise ValueError('Successful matching prerequisite required')
        return result['result'], run_root / task_id

    if task['role'] == 'intelligence' and task['action'] == 'review_single' and 'from_task' in payload:
        if set(payload) != {'from_task'}:
            raise ValueError('Do not mix handoff and inline evidence')
        result, prior_root = prior(payload['from_task'], 'research')
        handoff = read_json(prior_root / 'handoff.json')
        if (result.get('handoff_file') != 'handoff.json' or digest(handoff) != result.get('handoff_hash')
                or set(handoff) != {'schema', 'plan', 'selected'} or handoff['schema'] != 'diamond.review-handoff/1'):
            raise ValueError('Research handoff integrity check failed')
        task['payload'] = {k: handoff[k] for k in ('plan', 'selected')}
    if task['role'] == 'testing' and 'proposal_from' in payload:
        if set(payload) != {'pattern', 'proposal_from'}:
            raise ValueError('Testing proposal requires only pattern and prerequisite')
        result, prior_root = prior(payload['proposal_from'], 'coding')
        target = result.get('target')
        if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_]+\.py', target) or target not in snapshot:
            raise ValueError('Invalid proposal target')
        path = prior_root / 'proposed.py'
        if result.get('proposal_file') != 'proposed.py' or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('Bounded regular proposal required')
        data = path.read_bytes()
        if (hashlib.sha256(data).hexdigest() != result.get('proposed_sha256')
                or hashlib.sha256(snapshot[target]).hexdigest() != result.get('original_sha256')):
            raise ValueError('Coding proposal integrity check failed')
        ast.parse(data)
        (root / 'src' / target).write_bytes(data)
        task['payload'] = {'pattern': payload['pattern']}
        task['_tested_proposal'] = {'target': target, 'sha256': result['proposed_sha256'],
                                    'applied_to_repository': False}
    return task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--tasks', type=Path)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    if bool(args.tasks) == args.demo:
        parser.error('Choose exactly one of --tasks or --demo')
    if args.demo:
        plan, selected = demo_inputs()
        code = (args.source / 'universe.py').read_bytes()
        tasks = [
            {'id': 'coding', 'role': 'coding', 'action': 'propose_edit', 'payload': {
                'path': 'universe.py', 'expected_sha256': hashlib.sha256(code).hexdigest(),
                'before': 'Canonical Diamond Mind Universe taxonomy used by Diamond Core.',
                'after': 'Canonical Diamond Mind Universe taxonomy shared by supervised workers.'}},
            {'id': 'research', 'role': 'research', 'action': 'extract', 'payload': {
                'selected': selected, 'projects': plan['projects'], 'reviewed_at': plan['reviewed_at'],
                'input_kind': 'synthetic'}},
            {'id': 'testing', 'role': 'testing', 'action': 'unittest',
             'payload': {'pattern': 'test_acceleration_independent.py'}},
            {'id': 'intelligence', 'role': 'intelligence', 'action': 'cycle',
             'payload': {'plan': plan, 'selected': selected}, 'depends_on': ['research', 'testing']},
        ]
    else:
        tasks = read_json(args.tasks)
    summary = coordinate(tasks, args.source, args.destination, args.timeout)
    print(json.dumps(summary, indent=2))
    if any(t['state'] != 'completed' for t in summary['tasks']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
