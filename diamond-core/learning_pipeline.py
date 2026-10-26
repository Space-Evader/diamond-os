"""Supervised learning from explicit approved sources, entirely noncanonical.

Extraction is deterministic and extractive, not model reasoning. Connections
are supplied hypotheses, never automatic corroboration. No network or legacy
Core modules are invoked. CLI output contains counts/hashes, never email text.
"""
import argparse
import copy
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from core_intake import STORE, _packets, submit_envelope
from discovery_review import digest, nonempty, timestamp, validate_history, validate_source
from review_store import atomic_json_create, store_lock
from source_policy import SOURCES, validate_registered_source
from universe import canonical_project_name

RELATIONS = {'support', 'contradiction', 'analogy'}
DECISIONS = {'useful', 'not_useful', 'needs_work'}
HASH = re.compile(r'[0-9a-f]{64}')
URL = re.compile(r'https?://\S+', re.I)
BOILERPLATE = re.compile(
    r'^(?:hi\b|hello\b|hey\b|good (?:morning|afternoon|evening)\b|welcome\b'
    r'|(?:in |inside |on )?(?:today[’\']s|this week[’\']s|this) (?:newsletter|issue|edition)\b'
    r'|in (?:today[’\']s|this week[’\']s|this week|this issue|this edition)\b'
    r'|today[’\']s (?:highlights|headlines|roundup)\b'
    r'|(?:you[’\']re|you are) reading\b'
    r'|(?:thanks?|thank you) for (?:reading|subscribing|joining)\b'
    r'|(?:here[’\']s|here is) (?:what[’\']s|what is|your)\b'
    r'|(?:in partnership|together|presented|sponsored) (?:with|by)\b'
    r'|(?:read more|sign up|subscribe|manage preferences|view in browser|unsubscribe)\b'
    r'|(?:what[’\']s inside|contents|table of contents|from our sponsor)\b'
    r'|you (?:are|[’\']re) receiving\b|sent (?:to|by)\b|copyright\b|all rights reserved\b)',
    re.I,
)
ASSERTION = re.compile(
    r'\b(?:is|are|was|were|has|have|had|will|could|can|may|might|should|would|must'
    r'|found|finds|shows?|showed|suggests?|reported|reports?|reveals?|released?|launched?'
    r'|measures?|measured|explains?|helps?|allows?|requires?|research|study|scientists?)\b',
    re.I,
)


def is_boilerplate(text):
    """Conservative editorial/marketing markers, never a relevance judgment."""
    text = text.strip(' \t•*-_>📌')
    letters = ''.join(c for c in text if c.isalpha())
    return (bool(BOILERPLATE.search(text))
            or bool(letters and letters.isupper() and not text.endswith(('.', '!', '?')))
            or (len(text) <= 120 and text.endswith(':')))


def text_spans(content):
    """Yield original URL-free spans; inline provenance never discards prose."""
    for match in re.finditer(r'[^\n]+', content):
        line = match.group()
        if is_boilerplate(line):
            continue
        offset = 0
        for url in URL.finditer(line):
            yield match.start() + offset, line[offset:url.start()]
            offset = url.end()
        yield match.start() + offset, line[offset:]


def now():
    return datetime.now(timezone.utc).isoformat()


def normalized_hash(text):
    return digest(' '.join(text.casefold().split()))


def extract_envelope(source, approval, analyst, reviewed_at, projects, max_ideas=3, *, explicit_spans=None):
    """Select exact short text spans as unverified publisher assertions."""
    validate_source(source, approval)
    validate_registered_source(source, source.get('source_id'))
    if type(max_ideas) is not int or not 1 <= max_ideas <= 5:
        raise ValueError('max_ideas must be 1..5')
    if not isinstance(projects, list) or not projects:
        raise ValueError('At least one existing project required')
    projects = list(dict.fromkeys(canonical_project_name(p) for p in projects))
    if not nonempty(analyst):
        raise ValueError('Analyst identity required')
    timestamp(reviewed_at)
    content = source['content']
    if len(content) > 1_000_000:
        raise ValueError('Source exceeds the bounded one-million-character intake limit')
    candidates, seen = [], set()
    for span_start, original in (text_spans(content) if explicit_spans is None else []):
        line = original.strip()
        if (len(line) < 45 or not re.search(r'[A-Za-z]{3}', line)
                or is_boilerplate(line)
                or re.search(r'unsubscribe|view in browser|manage preferences|sponsored|advertisement',
                             line, re.I)):
            continue
        excerpt = line[:240]
        if len(line) > 240 and ' ' in excerpt:
            excerpt = excerpt.rsplit(' ', 1)[0]
        fingerprint = normalized_hash(excerpt)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        start = span_start + len(original) - len(original.lstrip())
        # Prefer attributed prose to link-adjacent navigation/headline fragments.
        # This is a deterministic formatting heuristic, not a truth judgment.
        score = 3 * bool(ASSERTION.search(line)) + bool(line.endswith(('.', '!', '?')))
        candidates.append((excerpt, start, score))
    if explicit_spans is not None:
        if not isinstance(explicit_spans, list) or not 1 <= len(explicit_spans) <= 3:
            raise ValueError('Select one to three exact evidence spans')
        for span in explicit_spans:
            if (not isinstance(span, dict) or set(span) != {'start', 'end'}
                    or type(span['start']) is not int or type(span['end']) is not int
                    or not 0 <= span['start'] < span['end'] <= len(content)
                    or span['end'] - span['start'] > 240):
                raise ValueError('Bounded source character offsets required')
            start, end = span['start'], span['end']
            excerpt = content[start:end]
            if not excerpt.strip() or any(start < pos + len(text) and pos < end
                                          for text, pos, _ in candidates):
                raise ValueError('Select distinct nonempty evidence spans')
            candidates.append((excerpt, start, 0))
    if not candidates:
        raise ValueError('No suitable text spans; select a permitted excerpt for manual review')
    candidates = sorted(candidates, key=lambda item: (-item[2], item[1]))[:max_ideas]
    metadata = copy.deepcopy(source)
    metadata['normalized_content_hash'] = normalized_hash(content)
    metadata['extraction_method'] = 'bounded-extractive-lines/2'
    metadata['evidence_spans'] = [
        {'start': start, 'end': start + len(excerpt), 'excerpt_hash': digest(excerpt)}
        for excerpt, start, _ in candidates
    ]
    ideas = [
        {'statement': 'Unverified publisher assertion: ' + excerpt,
         'kind': 'provisional_interpretation', 'evidence_state': 'UNRESOLVED',
         'excerpt': excerpt, 'locator': f'characters:{start}:{start + len(excerpt)}'}
        for excerpt, start, _ in candidates
    ]
    return {
        'source': metadata, 'approval': copy.deepcopy(approval), 'analyst': analyst,
        'reviewed_at': reviewed_at,
        'analysis': {
            'ideas': ideas, 'projects': projects,
            'discovery': {
                'connection': 'Candidate material for ' + ', '.join(projects) + '; relevance awaits review.',
                'why_it_matters': 'A bounded review can identify a concrete experiment without treating publication claims as facts.',
                'support': 'Exact character spans in the selected source support attribution only.',
                'challenge': 'The selected lines may lack context, independent evidence, or practical relevance.',
                'next_step': 'Review the attributed spans; record usefulness and a specific project experiment before action.',
            },
            'dissent': ['Publication identity does not verify its assertions. Extractive selection may miss contrary context.'],
            'questions': ['What independent evidence and measurable project result would justify using this idea?'],
        },
    }


def latest_packets(packets):
    packets = list(packets)
    validate_history(packets)
    latest = {}
    for packet in packets:
        key = packet['source_key']
        if key not in latest or packet['revision'] > latest[key]['revision']:
            latest[key] = packet
    return latest


def lineage(packet):
    """Exact/whitespace-normalized duplicate content is one evidence lineage."""
    value = packet['source'].get('normalized_content_hash', packet['content_hash'])
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError('Invalid normalized content identity')
    return value


def duplicate_groups(packets):
    grouped = {}
    for packet in latest_packets(packets).values():
        grouped.setdefault(lineage(packet), []).append(packet['packet_hash'])
    return [{'content_identity': key, 'packet_hashes': sorted(values),
             'evidence_lineages': 1}
            for key, values in sorted(grouped.items()) if len(values) > 1]


def require_text(value, label):
    if not nonempty(value) or len(value) > 4000:
        raise ValueError(label + ' must be a nonempty string of at most 4000 characters')


def synthesize(packets, packet_hashes, relation, hypothesis, challenge, next_step,
               reviewer, instruction_ref, reviewed_at):
    latest = latest_packets(packets)
    current = {p['packet_hash']: p for p in latest.values()}
    if (not isinstance(packet_hashes, list) or len(packet_hashes) < 2
            or not all(isinstance(h, str) and HASH.fullmatch(h) for h in packet_hashes)
            or len(set(packet_hashes)) != len(packet_hashes)):
        raise ValueError('At least two distinct current packet hashes required')
    if any(h not in current for h in packet_hashes):
        raise ValueError('Synthesis requires exact current packet revisions')
    if relation not in RELATIONS:
        raise ValueError('Unsupported source relationship')
    for value, label in ((hypothesis, 'Hypothesis'), (challenge, 'Challenge'), (next_step, 'Next step'),
                         (reviewer, 'Reviewer'), (instruction_ref, 'Instruction reference')):
        require_text(value, label)
    timestamp(reviewed_at)
    selected = [current[h] for h in sorted(packet_hashes)]
    lineages = len({lineage(p) for p in selected})
    if relation == 'support' and lineages < 2:
        raise ValueError('Distinct evidence lineages required for support; duplicate text is not corroboration')
    record = {
        'schema': 'dmio.discovery.connection/1', 'canonical': False, 'review_required': True,
        'relation': relation, 'hypothesis': hypothesis, 'challenge': challenge, 'next_step': next_step,
        'reviewer': reviewer, 'instruction_ref': instruction_ref, 'reviewed_at': reviewed_at,
        'interpretation_status': 'hypothesis_pending_owner_review',
        'independent_verification_established': False, 'evidence_lineages': lineages,
        'references': [
            {k: p[k] for k in ('packet_hash', 'source_key', 'revision', 'content_hash')}
            for p in selected
        ],
    }
    record['connection_hash'] = digest(record)
    return record


def validate_synthesis(record, packets):
    packets = list(packets)
    latest = latest_packets(packets)
    historical = {p['packet_hash']: p for p in packets}
    if (not isinstance(record, dict) or record.get('schema') != 'dmio.discovery.connection/1'
            or record.get('canonical') is not False or record.get('review_required') is not True
            or record.get('independent_verification_established') is not False
            or record.get('interpretation_status') != 'hypothesis_pending_owner_review'):
        raise ValueError('Invalid review-only connection')
    if record.get('connection_hash') != digest({k: v for k, v in record.items() if k != 'connection_hash'}):
        raise ValueError('Connection content changed')
    if record.get('relation') not in RELATIONS:
        raise ValueError('Invalid source relationship')
    for key in ('hypothesis', 'challenge', 'next_step', 'reviewer', 'instruction_ref'):
        require_text(record.get(key), key)
    timestamp(record.get('reviewed_at'))
    refs = record.get('references')
    if not isinstance(refs, list) or len(refs) < 2:
        raise ValueError('Connection needs at least two packet references')
    hashes, source_keys, selected, stale = set(), set(), [], []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'packet_hash', 'source_key', 'revision', 'content_hash'}:
            raise ValueError('Invalid connection reference shape')
        p = historical.get(ref['packet_hash'])
        if (p is None or any(ref[k] != p[k] for k in ref)
                or ref['packet_hash'] in hashes or ref['source_key'] in source_keys):
            raise ValueError('Connection references missing, duplicate, or changed evidence')
        hashes.add(ref['packet_hash'])
        source_keys.add(ref['source_key'])
        selected.append(p)
        if latest[p['source_key']]['packet_hash'] != p['packet_hash']:
            stale.append(p['packet_hash'])
    count = len({lineage(p) for p in selected})
    if type(record.get('evidence_lineages')) is not int or record['evidence_lineages'] != count:
        raise ValueError('Connection evidence-lineage count changed')
    if record['relation'] == 'support' and count < 2:
        raise ValueError('Duplicate content cannot establish support')
    return {'stale': bool(stale), 'superseded_references': sorted(stale)}


def _load_connections(store, packets):
    records = []
    for path in sorted(Path(store).glob('connection_*.json')):
        if path.is_symlink():
            raise ValueError('Connection records cannot be symbolic links')
        record = json.loads(path.read_text(encoding='utf-8'))
        validate_synthesis(record, packets)
        if path.name != f"connection_{record['connection_hash']}.json":
            raise ValueError('Connection filename identity mismatch')
        records.append(record)
    return records


def load_feedback(store, packets, connections):
    targets = {p['packet_hash'] for p in packets} | {c['connection_hash'] for c in connections}
    result = []
    for path in sorted(Path(store).glob('feedback_*.json')):
        if path.is_symlink():
            raise ValueError('Feedback records cannot be symbolic links')
        record = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(record, dict) or record.get('schema') != 'dmio.discovery.feedback/1'
                or record.get('canonical') is not False or record.get('review_required') is not True
                or record.get('target_hash') not in targets or record.get('decision') not in DECISIONS):
            raise ValueError('Invalid noncanonical feedback event')
        for key in ('note', 'reviewer', 'instruction_ref'):
            require_text(record.get(key), key)
        timestamp(record.get('reviewed_at'))
        if record.get('event_hash') != digest({k: v for k, v in record.items() if k != 'event_hash'}):
            raise ValueError('Feedback content changed')
        if path.name != f"feedback_{record['event_hash']}.json":
            raise ValueError('Feedback filename identity mismatch')
        result.append(record)
    return result


def read_state(store):
    with store_lock(store):
        packets = [p for _, p in _packets(Path(store))]
        connections = _load_connections(store, packets)
        feedback = load_feedback(store, packets, connections)
    return packets, connections, feedback


def save_synthesis(store, **kwargs):
    with store_lock(store):
        packets = [p for _, p in _packets(Path(store))]
        _load_connections(store, packets)
        record = synthesize(packets, **kwargs)
        path = Path(store) / f"connection_{record['connection_hash']}.json"
        atomic_json_create(path, record)
        return record, path


def record_feedback(target_hash, decision, note, reviewer, instruction_ref, reviewed_at, store):
    if decision not in DECISIONS:
        raise ValueError('Unsupported usefulness decision')
    for value, label in ((note, 'Note'), (reviewer, 'Reviewer'), (instruction_ref, 'Instruction reference')):
        require_text(value, label)
    timestamp(reviewed_at)
    with store_lock(store):
        packets = [p for _, p in _packets(Path(store))]
        connections = _load_connections(store, packets)
        load_feedback(store, packets, connections)
        if target_hash not in ({p['packet_hash'] for p in packets} | {c['connection_hash'] for c in connections}):
            raise ValueError('Feedback must reference an existing exact packet or connection hash')
        record = {
            'schema': 'dmio.discovery.feedback/1', 'canonical': False, 'review_required': True,
            'target_hash': target_hash, 'decision': decision, 'note': note, 'reviewer': reviewer,
            'instruction_ref': instruction_ref, 'reviewed_at': reviewed_at,
        }
        record['event_hash'] = digest(record)
        path = Path(store) / f"feedback_{record['event_hash']}.json"
        if not path.exists():
            atomic_json_create(path, record)
        return record, path


def status(store):
    packets, connections, feedback = read_state(store)
    current_feedback = {}
    for event in sorted(feedback, key=lambda e: (datetime.fromisoformat(e['reviewed_at'].replace('Z', '+00:00')), e['event_hash'])):
        current_feedback[event['target_hash']] = event
    return {
        'packet_revisions': len(packets), 'current_sources': len(latest_packets(packets)),
        'duplicate_content_groups': len(duplicate_groups(packets)),
        'connections': len(connections),
        'stale_connections': sum(validate_synthesis(c, packets)['stale'] for c in connections),
        'feedback_events': len(feedback),
        'latest_feedback_decisions': dict(Counter(e['decision'] for e in current_feedback.values())),
        'canonical_records': sum(p['canonical'] for p in packets + connections + feedback),
        'email_sources_enabled': [key for key, p in SOURCES.items() if p['email_enabled']],
        'email_sources_pending_identity': [key for key, p in SOURCES.items() if not p['email_enabled']],
        'mode': 'supervised_review_only',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=STORE)
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest', help='Extract and save one selected registered source for review')
    ingest.add_argument('input', type=Path)
    ingest.add_argument('--project', action='append', required=True)
    ingest.add_argument('--analyst', required=True)
    ingest.add_argument('--confirm-review-only', action='store_true', required=True)
    sub.add_parser('status', help='Aggregate metadata only; no private text')
    sub.add_parser('duplicates', help='Identify identical content across selected sources')
    connect = sub.add_parser('connect', help='Record a supplied cross-source hypothesis')
    connect.add_argument('--packet', action='append', required=True)
    connect.add_argument('--relation', choices=sorted(RELATIONS), required=True)
    connect.add_argument('--hypothesis', required=True)
    connect.add_argument('--challenge', required=True)
    connect.add_argument('--next-step', required=True)
    connect.add_argument('--reviewer', required=True)
    connect.add_argument('--instruction-ref', required=True)
    connect.add_argument('--confirm-review-only', action='store_true', required=True)
    feedback = sub.add_parser('feedback', help='Append usefulness feedback; never promote')
    feedback.add_argument('--target', required=True)
    feedback.add_argument('--decision', choices=sorted(DECISIONS), required=True)
    feedback.add_argument('--note', required=True)
    feedback.add_argument('--reviewer', required=True)
    feedback.add_argument('--instruction-ref', required=True)
    feedback.add_argument('--confirm-review-only', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'ingest':
        selected = json.loads(args.input.read_text(encoding='utf-8-sig'))
        envelope = extract_envelope(selected['source'], selected['approval'], args.analyst, now(), args.project)
        packet, result, _ = submit_envelope(envelope, args.store)
        output = {'result': result, 'packet_hash': packet['packet_hash'], 'revision': packet['revision'],
                  'extracted_ideas': len(packet['analysis']['ideas']), 'canonical': False}
    elif args.command == 'connect':
        record, _ = save_synthesis(
            args.store, packet_hashes=args.packet, relation=args.relation, hypothesis=args.hypothesis,
            challenge=args.challenge, next_step=args.next_step, reviewer=args.reviewer,
            instruction_ref=args.instruction_ref, reviewed_at=now())
        output = {'connection_hash': record['connection_hash'], 'evidence_lineages': record['evidence_lineages'],
                  'canonical': False, 'review_required': True}
    elif args.command == 'feedback':
        record, _ = record_feedback(args.target, args.decision, args.note, args.reviewer,
                                    args.instruction_ref, now(), args.store)
        output = {'event_hash': record['event_hash'], 'canonical': False, 'review_required': True}
    elif args.command == 'duplicates':
        output = duplicate_groups(read_state(args.store)[0])
    else:
        output = status(args.store)
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
