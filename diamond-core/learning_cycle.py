"""Repeatable, explicit review-only cycles. No scheduler or canonical promotion.

Plans and selected input files are trusted operator configuration; source bodies
remain untrusted evidence. A declaration of real input does not verify a claim.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from core_intake import submit_envelope
from discovery_review import digest, timestamp
from learning_pipeline import (DECISIONS, RELATIONS, extract_envelope, read_state,
                               record_feedback, save_synthesis, status)
from review_store import atomic_json_create, store_lock
from source_policy import account_message_ref

MAX_BYTES = 2_000_000


def read_json(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Input must be a bounded regular JSON file, not a symlink')
    if not path.is_file():
        raise ValueError('Regular file required')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def private_directory(path):
    """Keep review state outside every Git checkout; reject symlinked parents."""
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Private paths cannot contain symbolic links')
        marker = parent / '.git'
        if marker.is_file() or (marker / 'HEAD').is_file():
            raise ValueError('Private state must be outside a Git checkout')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix' and path.stat().st_mode & 0o077:
        raise ValueError('Private directory must have user-only permissions')
    return path


def validate_plan(plan):
    fields = {'schema', 'input_kind', 'reviewed_at', 'projects', 'reviewer',
              'instruction_ref', 'synthesis', 'feedback'}
    if not isinstance(plan, dict) or set(plan) != fields or plan['schema'] != 'diamond.cycle/1':
        raise ValueError('Exact diamond.cycle/1 plan required')
    if plan['input_kind'] not in ('synthetic', 'real'):
        raise ValueError('Declare synthetic or real input; real does not mean verified')
    timestamp(plan['reviewed_at'])
    for name in ('reviewer', 'instruction_ref'):
        if not isinstance(plan[name], str) or not plan[name].strip():
            raise ValueError('Reviewer and instruction reference required')
    syn, feedback = plan['synthesis'], plan['feedback']
    if not isinstance(syn, dict) or set(syn) != {'relation', 'hypothesis', 'challenge', 'next_step'}:
        raise ValueError('Explicit hypothesis, challenge and experiment required')
    if syn['relation'] not in RELATIONS:
        raise ValueError('Unsupported relationship')
    if not isinstance(feedback, dict) or set(feedback) != {'decision', 'note'}:
        raise ValueError('Explicit review feedback required')
    if feedback['decision'] not in DECISIONS:
        raise ValueError('Unsupported feedback decision')
    for value in [syn[k] for k in ('hypothesis', 'challenge', 'next_step')] + [feedback['note']]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Empty review text')


def run_cycle(plan, selected, store):
    """Prevalidate all inputs before writes. Stable plan time makes replay safe.

    Interrupted cycles can be resumed with the same plan and inputs. Publication
    is atomic per record, not a transaction over the entire cycle.
    """
    validate_plan(plan)
    if not isinstance(selected, list) or not 2 <= len(selected) <= 8:
        raise ValueError('A complete synthesis cycle requires two to eight selected inputs')
    envelopes = []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {'source', 'approval'}:
            raise ValueError('Selected input requires source and approval only')
        envelopes.append(extract_envelope(item['source'], item['approval'], plan['reviewer'],
                                          plan['reviewed_at'], plan['projects']))
    refs = [e['source']['ref'] for e in envelopes]
    if len(set(refs)) != len(refs):
        raise ValueError('Select distinct source references')
    # Validate synthesis before storing any input, including duplicate-lineage rules.
    from discovery_review import prepare
    from learning_pipeline import synthesize
    preview = [prepare(**e)[0] for e in envelopes]
    kwargs = dict(plan['synthesis'], packet_hashes=[p['packet_hash'] for p in preview],
                  reviewer=plan['reviewer'], instruction_ref=plan['instruction_ref'],
                  reviewed_at=plan['reviewed_at'])
    synthesize(preview, **kwargs)
    store = private_directory(store)
    cycle_id = digest({'plan': plan, 'selected': selected})
    # Separate coordination lock; inner components retain their own storage locks.
    with store_lock(store / 'cycles'):
        receipt_path = store / 'cycles' / (cycle_id + '.json')
        if receipt_path.exists():
            saved = read_json(receipt_path)
            current_status = status(store)  # Validate all available history before replay.
            if saved.get('cycle_id') != cycle_id or saved.get('canonical') is not False:
                raise ValueError('Invalid cycle receipt')
            saved.update(repeated_cycle=True, receipt_replayed=True, status=current_status)
            for result in saved['ingests']:
                result['result'] = 'not_ingested_receipt_replay'
            return saved
        packets, results = [], []
        for envelope in envelopes:
            packet, result, _ = submit_envelope(envelope, store)
            _, replay, _ = submit_envelope(envelope, store)
            packets.append(packet)
            results.append({'result': result, 'replay': replay, 'packet_hash': packet['packet_hash']})
        kwargs['packet_hashes'] = [p['packet_hash'] for p in packets]
        # Reuse an identical connection after interrupted or repeated execution.
        current, connections, _ = read_state(store)
        expected = synthesize(current, **kwargs)
        connection = next((c for c in connections if c == expected), None)
        if connection is None:
            connection, _ = save_synthesis(store, **kwargs)
        feedback, _ = record_feedback(connection['connection_hash'], plan['feedback']['decision'],
                                      plan['feedback']['note'], plan['reviewer'],
                                      plan['instruction_ref'], plan['reviewed_at'], store)
        report = {'cycle_id': cycle_id, 'input_kind': plan['input_kind'],
                  'input_provenance': 'operator-declared; not independently verified',
                  'ingests': results, 'connection_hash': connection['connection_hash'],
                  'feedback_hash': feedback['event_hash'], 'canonical': False,
                  'review_required': True, 'status': status(store)}
        if not receipt_path.exists():
            atomic_json_create(receipt_path, report)
        report['repeated_cycle'] = all(r['result'] == 'duplicate' for r in results)
        report['receipt_replayed'] = False
        return report


def demo_inputs():
    """Invented representative prose, not publisher reporting or live retrieval."""
    texts = (
        'Researchers reported that a small review queue reduced the delay between reading evidence and designing an experiment.',
        'A separate hypothetical team found that writing a counterargument exposed assumptions before they tested a proposed application.',
    )
    selected = []
    for i, text in enumerate(texts, 1):
        ref = f'https://nautil.us/synthetic-diamond-cycle-{i}/'
        selected.append({'source': {'kind': 'document', 'source_id': 'nautilus', 'ref': ref,
                         'title': f'SYNTHETIC fixture {i}', 'creator': 'Invented fixture, not Nautilus',
                         'captured_at': '2026-10-26T12:00:00+00:00',
                         'access_basis': 'Synthetic integration fixture; no retrieval', 'content': text},
                         'approval': {'source_ref': ref, 'scope': 'review_only',
                                      'instruction_ref': 'Offline demonstration only'}})
    plan = {'schema': 'diamond.cycle/1', 'input_kind': 'synthetic',
            'reviewed_at': '2026-10-26T12:01:00+00:00', 'projects': ['Diamond Core'],
            'reviewer': 'Offline demonstration worker', 'instruction_ref': 'Offline demonstration only',
            'synthesis': {'relation': 'analogy',
                          'hypothesis': 'A bounded queue plus a counterargument may shorten source-to-experiment time.',
                          'challenge': 'Synthetic examples establish no real-world benefit.',
                          'next_step': 'With one approved live source, measure minutes to one hypothesis and counterargument.'},
            'feedback': {'decision': 'needs_work', 'note': 'Requires real evidence and a measured outcome.'}}
    return plan, selected


def select_message(source, message_id, account_ref, instruction_ref, store, token_file):
    """Use the recovered exact-sender selector with external, existing OAuth only.

    Never initiates interactive login or writes credentials beside source files.
    The optional libraries are imported only after private-path validation.
    """
    import gmail_review_select as selector
    from unittest.mock import patch
    store = private_directory(store)
    token_file = Path(token_file).absolute()
    private_directory(token_file.parent)
    if token_file.is_symlink() or not token_file.is_file():
        raise ValueError('Existing external OAuth token file required')
    if os.name == 'posix' and token_file.stat().st_mode & 0o077:
        raise ValueError('Token file must have user-only permissions')

    def external_service():
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(token_file), selector.SCOPES)
        if not creds.valid:
            if not creds.expired or not creds.refresh_token:
                raise ValueError('Existing read-only authorization requires renewal outside this command')
            creds.refresh(Request())
        if not creds.has_scopes(selector.SCOPES):
            raise ValueError('Existing Gmail read-only scope required')
        return build('gmail', 'v1', credentials=creds, cache_discovery=False)

    args = SimpleNamespace(source=source, id=message_id, account_ref=account_ref,
                           instruction_ref=instruction_ref, confirm_review_only=True)
    with patch.object(selector, 'STORE', store), patch.object(selector, 'service', external_service):
        with contextlib.redirect_stdout(io.StringIO()):
            selector.select_approved(args)
    ref = account_message_ref(account_ref, message_id)
    return store / ('gmail_approved_' + hashlib.sha256(ref.encode()).hexdigest() + '.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='Complete offline cycle with invented evidence')
    demo.add_argument('--store', type=Path, required=True)
    run = sub.add_parser('run', help='Cycle using explicit selected envelopes and a review plan')
    run.add_argument('--store', type=Path, required=True)
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--input', type=Path, action='append', required=True)
    run.add_argument('--confirm-review-only', action='store_true', required=True)
    select = sub.add_parser('select', help='Stage one exact approved Gmail message; existing OAuth only')
    for name in ('source', 'id', 'account-ref', 'instruction-ref', 'token-file', 'store'):
        select.add_argument('--' + name, required=True)
    select.add_argument('--confirm-review-only', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'demo':
        plan, inputs = demo_inputs()
        result = run_cycle(plan, inputs, args.store)
    elif args.command == 'run':
        result = run_cycle(read_json(args.plan), [read_json(p) for p in args.input], args.store)
    else:
        path = select_message(args.source, args.id, args.account_ref, args.instruction_ref,
                              args.store, args.token_file)
        result = {'staged_file': path.name, 'canonical': False, 'review_required': True}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
