"""Behavioral proof for the existing offline CLI, not a replacement test runner."""
import json
from pathlib import Path
import subprocess
import sys

from discovery_review import digest
from review_store import atomic_json_create


def verify_cycle_cli(root):
    root = Path(root).resolve()
    command = [sys.executable, '-B', str(root / 'src' / 'learning_cycle.py'),
               'demo', '--store', str(root / 'behavioral-reviews')]
    runs = []
    for _ in range(2):
        result = subprocess.run(command, cwd=root, input='',
                                capture_output=True, text=True, timeout=10, check=True)
        if len(result.stdout) > 100_000:
            raise ValueError('Excessive CLI output')
        runs.append(json.loads(result.stdout))
    first, second = runs
    for report in runs:
        if report['canonical'] is not False or report['input_kind'] != 'synthetic':
            raise ValueError('CLI review boundary failed')
        state = report['status']
        if any(state[k] != v for k, v in {'packet_revisions': 2, 'connections': 1,
                                         'feedback_events': 1, 'canonical_records': 0}.items()):
            raise ValueError('CLI did not produce the expected private review records')
    if (first['receipt_replayed'] or not second['receipt_replayed']
            or first['cycle_id'] != second['cycle_id']
            or first['connection_hash'] != second['connection_hash']
            or first['feedback_hash'] != second['feedback_hash']
            or any(r['result'] != 'new' or r['replay'] != 'duplicate' for r in first['ingests'])
            or len(first['ingests']) != 2):
        raise ValueError('CLI replay proof failed')
    # Inspect the actual stored state as well as stdout; fabricated summaries are insufficient.
    from learning_pipeline import status
    if status(root / 'behavioral-reviews') != second['status']:
        raise ValueError('CLI summary does not match stored records')
    proof = {'schema': 'diamond.behavior-proof/1', 'successful': True,
             'command': 'learning_cycle.py demo (twice)', 'executions': 2,
             'input_kind': 'synthetic', 'state': second['status'],
             'receipt_replay_verified': True, 'stdout_hashes': [digest(r) for r in runs],
             'canonical': False, 'review_required': True}
    atomic_json_create(root / 'behavior-proof.json', proof)
    return {'successful': True, 'proof_file': 'behavior-proof.json', 'proof_hash': digest(proof),
            'executions': 2, 'input_kind': 'synthetic', 'canonical_records': 0}
