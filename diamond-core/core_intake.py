"""Founder-invoked, review-only intake for Diamond Core. No network or canonical writes.
Approval fields are declarations, not identity authentication.
"""
import argparse
import json
from pathlib import Path
from discovery_review import build_prompt, prepare, validate_packet, validate_source, search, validate_history

from review_store import atomic_json_create, store_lock

ROOT = Path(__file__).resolve().parent
STORE = ROOT / 'discovery_reviews'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def _packets(store):
    result = []
    for path in sorted(store.glob('intake_*.json')):
        if path.is_symlink():
            raise ValueError('Review records cannot be symbolic links')
        item = read(path)
        if not isinstance(item, dict) or not isinstance(item.get('packet'), dict):
            raise ValueError('Invalid review record envelope')
        p = validate_packet(item['packet'])
        expected = f"intake_{p['source_key'][:16]}_r{p['revision']:04d}.json"
        if path.name != expected:
            raise ValueError('Review filename does not match packet identity')
        if item.get('result') != ('new' if p['revision'] == 1 else 'new_revision'):
            raise ValueError('Review record result does not match revision')
        result.append((path, p))
    validate_history([p for _, p in result])
    return result


def packets(store=None):
    """Read records only after validating every available revision chain."""
    store = Path(STORE if store is None else store)
    if not store.exists():
        return []
    with store_lock(store):
        return _packets(store)


def submit_envelope(data, store=None):
    """Return (packet, status, path_or_None) after a serialized safe append."""
    if not isinstance(data, dict) or set(data) != {'source', 'approval', 'analysis', 'analyst', 'reviewed_at'}:
        raise ValueError('Review envelope requires source, approval, analysis, analyst and reviewed_at')
    # Validate before creating the store or acquiring its lock.
    prepare(**data)
    store = Path(STORE if store is None else store)
    source = data['source']
    with store_lock(store):
        prior = [p for _, p in _packets(store)
                 if p['source']['ref'] == source['ref'] and p['source']['kind'] == source['kind']]
        prior.sort(key=lambda p: p['revision'])
        previous = prior[-1] if prior else None
        packet, status = prepare(**data, previous=previous)
        if status == 'duplicate':
            return packet, status, None
        path = store / f"intake_{packet['source_key'][:16]}_r{packet['revision']:04d}.json"
        atomic_json_create(path, {'result': status, 'packet': packet})
        return packet, status, path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prompt', help='Display prompt for explicitly approved source')
    p.add_argument('input')
    p = sub.add_parser('submit', help='Validate and store an analyzed source, noncanonically')
    p.add_argument('input')
    p.add_argument('--confirm-review-only', action='store_true', required=True)
    p = sub.add_parser('list', help='Show saved review packet metadata')
    p = sub.add_parser('search', help='Search saved review packets')
    p.add_argument('query')
    args = parser.parse_args()
    if args.command == 'prompt':
        data = read(args.input)
        print(build_prompt(data['source'], data['approval']))
        return
    if args.command == 'submit':
        data = read(args.input)
        packet, status, path = submit_envelope(data)
        if status == 'duplicate':
            print('DUPLICATE: No file written.')
        else:
            print(f"SAVED: {path.name} | {status} | revision {packet['revision']} | canonical=False")
        return
    all_packets = packets()
    if args.command == 'list':
        for path, p in all_packets:
            print(f"{path.name} | revision={p['revision']} | source={p['source']['ref']} | review_required={p['review_required']}")
    else:
        hits = search([p for _, p in all_packets], args.query)
        for p in hits:
            print(f"revision={p['revision']} | source={p['source']['ref']} | connection={p['analysis']['discovery']['connection']}")
        print(f"MATCHES: {len(hits)}")

if __name__ == '__main__':
    main()

