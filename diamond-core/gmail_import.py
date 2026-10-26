"""Import one explicitly selected connected-Gmail snapshot or operator export.

No OAuth, mailbox search, network, credentials or HTML conversion. Snapshot
provenance is an operator declaration, not cryptographic sender authentication.
"""
import argparse
import hashlib
import json
from pathlib import Path

from discovery_review import digest, timestamp, validate_source
from gmail_review_select import message_body, published_timestamp, verified_headers
from learning_cycle import private_directory, read_json
from review_store import atomic_json_create, store_lock
from source_policy import account_message_ref, policy


def validate_selection(selection):
    fields = {'schema', 'source_id', 'message_id', 'account_ref', 'instruction_ref',
              'captured_at', 'transport'}
    if not isinstance(selection, dict) or set(selection) != fields or selection['schema'] != 'diamond.gmail-selection/1':
        raise ValueError('Explicit diamond.gmail-selection/1 required')
    if not policy(selection['source_id'])['email_enabled']:
        raise ValueError('Email source identity has not been verified')
    account_message_ref(selection['account_ref'], selection['message_id'])
    timestamp(selection['captured_at'])
    if not isinstance(selection['instruction_ref'], str) or not selection['instruction_ref'].strip():
        raise ValueError('Review-only instruction reference required')
    if selection['transport'] not in ('connected_gmail', 'operator_export'):
        raise ValueError('Declare actual snapshot transport')


def selected_envelope(selection, metadata, message):
    validate_selection(selection)
    # Identity is checked separately on the metadata and body-bearing snapshot.
    verified_headers(metadata, selection['message_id'], selection['source_id'])
    payload, headers = verified_headers(message, selection['message_id'], selection['source_id'])
    content = message_body(payload)
    if not content:
        raise ValueError('No permitted plain-text body; HTML and attachments are excluded')
    if len(content) > 1_000_000:
        raise ValueError('Message exceeds bounded intake limit')
    ref = account_message_ref(selection['account_ref'], selection['message_id'])
    source = {'kind': 'email', 'source_id': selection['source_id'], 'ref': ref,
              'message_id': selection['message_id'], 'account_ref': selection['account_ref'],
              'title': headers.get('subject') or '(No subject)', 'creator': headers['from'],
              'published_at': published_timestamp(headers.get('date')),
              'captured_at': selection['captured_at'],
              'access_basis': 'One explicitly selected message for supervised review-only import',
              'content': content,
              'capture_provenance': {'transport': selection['transport'],
                                     'authentication': 'operator-supplied snapshot; not independently authenticated',
                                     'metadata_hash': digest(metadata), 'message_hash': digest(message)}}
    approval = {'source_ref': ref, 'scope': 'review_only', 'instruction_ref': selection['instruction_ref']}
    validate_source(source, approval)
    return {'source': source, 'approval': approval}


def import_message(selection, metadata, message, store):
    envelope = selected_envelope(selection, metadata, message)
    store = private_directory(store)
    path = store / ('gmail_approved_' + hashlib.sha256(envelope['source']['ref'].encode()).hexdigest() + '.json')
    with store_lock(store):
        if path.exists():
            if read_json(path) != envelope:
                raise ValueError('Selected message already staged with different content or approval; use a separate capture store')
            return path, 'duplicate'
        atomic_json_create(path, envelope)
    return path, 'staged'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('selection', 'metadata', 'message', 'store'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--confirm-review-only', action='store_true', required=True)
    args = parser.parse_args()
    selection, metadata = read_json(args.selection), read_json(args.metadata)
    validate_selection(selection)
    # Reject metadata spoofing before even opening the full-message file.
    verified_headers(metadata, selection['message_id'], selection['source_id'])
    path, result = import_message(selection, metadata, read_json(args.message), args.store)
    print(json.dumps({'result': result, 'selected_file': path.name,
                      'canonical': False, 'review_required': True}))


if __name__ == '__main__':
    main()
