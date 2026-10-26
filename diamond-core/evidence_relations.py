"""Compare grounded, reviewer-indexed evidence; never infer truth from volume.

Story/claim keys and publisher independence are operator annotations. Repeated
text is detected automatically; semantic grouping requires reviewed keys.
"""
import argparse
import json
from collections import defaultdict

from discovery_review import validate_history
from learning_cycle import read_json
from learning_pipeline import latest_packets, lineage, normalized_hash
from universe import canonical_project_name

# Conservative independence buckets, not a claim about legal ownership.
# Related AI newsletters cannot be counted as independent by changing labels.
INDEPENDENCE_BUCKETS = {'nautilus': 'nautilus', 'superhuman': 'superhuman-network',
                        'the-code': 'superhuman-network'}


def analyze(packets, cards, independence_reviews=()):
    validate_history(packets)
    current = {p['packet_hash']: p for p in latest_packets(packets).values()}
    if not isinstance(cards, list) or not 1 <= len(cards) <= 64:
        raise ValueError('One to 64 reviewed evidence cards required')
    fields = {'id', 'packet_hash', 'idea_index', 'story_key', 'claim_key', 'stance'}
    indexed, stories, claims, excerpts = {}, defaultdict(list), defaultdict(list), defaultdict(list)
    for card in cards:
        if not isinstance(card, dict) or set(card) != fields:
            raise ValueError('Exact evidence card schema required')
        if any(not isinstance(card[k], str) or not card[k].strip() or len(card[k]) > 200
               for k in ('id', 'story_key', 'claim_key')) or card['id'] in indexed:
            raise ValueError('Unique bounded card IDs and grouping keys required')
        packet = current.get(card['packet_hash'])
        if packet is None or type(card['idea_index']) is not int or not 0 <= card['idea_index'] < len(packet['analysis']['ideas']):
            raise ValueError('Card must reference one current exact packet excerpt')
        if card['stance'] not in ('supports', 'disputes', 'uncertain'):
            raise ValueError('Invalid reported claim stance')
        indexed[card['id']] = (card, packet)
        stories[card['story_key']].append(card['id'])
        claims[card['claim_key']].append(card['id'])
        text = packet['analysis']['ideas'][card['idea_index']]['excerpt']
        excerpts[normalized_hash(text)].append(card['id'])
    repeated = []
    for story, ids in sorted(stories.items()):
        if len(ids) > 1:
            repeated.append({'story_key': story, 'cards': ids,
                             'distinct_sources': len({indexed[i][1]['source_key'] for i in ids}),
                             'independent_corroboration': False})
    conflicts = [{'claim_key': key, 'cards': ids, 'classification': 'reported_dispute_not_adjudicated'}
                 for key, ids in sorted(claims.items())
                 if {'supports', 'disputes'} <= {indexed[i][0]['stance'] for i in ids}]
    corroboration = []
    if not isinstance(independence_reviews, (list, tuple)) or len(independence_reviews) > 32:
        raise ValueError('Bounded independence reviews required')
    for review in independence_reviews:
        if not isinstance(review, dict) or set(review) != {'cards', 'publisher_groups', 'origin_refs', 'reviewer', 'rationale'}:
            raise ValueError('Explicit independence review required')
        ids = review['cards']
        if (not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2
                or any(i not in indexed for i in ids)):
            raise ValueError('Independence review requires two distinct known cards')
        for field in ('publisher_groups', 'origin_refs'):
            values = review[field]
            if (not isinstance(values, list) or len(values) != 2 or len(set(values)) != 2
                    or any(not isinstance(v, str) or not v.strip() for v in values)):
                raise ValueError('Distinct reviewed publishers and reporting origins required')
        if any(not isinstance(review[f], str) or not review[f].strip() for f in ('reviewer', 'rationale')):
            raise ValueError('Named reviewer and independence rationale required')
        pairs = [indexed[i] for i in ids]
        if (len({p['source_key'] for _, p in pairs}) != 2 or len({lineage(p) for _, p in pairs}) != 2
                or len({c['claim_key'] for c, _ in pairs}) != 1
                or any(c['stance'] != 'supports' for c, _ in pairs)):
            raise ValueError('Independent support requires distinct lineages supporting the same claim')
        if len({normalized_hash(p['analysis']['ideas'][c['idea_index']]['excerpt']) for c, p in pairs}) != 2:
            raise ValueError('Repeated reporting excerpts cannot establish independent support')
        buckets = [INDEPENDENCE_BUCKETS.get(p['source'].get('source_id')) for _, p in pairs]
        if None in buckets or len(set(buckets)) != 2 or review['publisher_groups'] != buckets:
            raise ValueError('Independence review conflicts with conservative source buckets')
        corroboration.append({'cards': ids, 'classification': 'reviewer_assessed_independent_support',
                              'claim_verified': False, 'rationale': review['rationale']})
    return {'repeated_stories': repeated,
            'repeated_excerpt_groups': [v for v in excerpts.values() if len(v) > 1],
            'conflicting_claims': conflicts, 'reviewed_independent_support': corroboration,
            'independence_status': 'reviewed' if corroboration else 'not_established',
            'grouping_basis': 'exact text plus operator-reviewed story and claim keys',
            'canonical': False, 'review_required': True}


def rank_candidates(candidates, cards, packets, feedback=()):
    """Transparent operator-estimated priority; not predicted ROI or truth score."""
    analyze(packets, cards)
    card_map = {c['id']: c for c in cards}
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 12:
        raise ValueError('One to 12 hypotheses required')
    results, seen = [], set()
    required = {'id', 'project', 'hypothesis', 'evidence_cards', 'uncertainty',
                'effort_hours', 'expected_value', 'risk'}
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != required:
            raise ValueError('Exact hypothesis schema required')
        for key in ('id', 'hypothesis', 'uncertainty'):
            if not isinstance(candidate[key], str) or not candidate[key].strip():
                raise ValueError('Named hypothesis and uncertainty required')
        if candidate['id'] in seen:
            raise ValueError('Duplicate candidate')
        seen.add(candidate['id'])
        refs = candidate['evidence_cards']
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or any(r not in card_map for r in refs):
            raise ValueError('Known unique evidence references required')
        effort = candidate['effort_hours']
        if not isinstance(effort, list) or len(effort) != 2 or any(type(e) not in (int, float) for e in effort) or not 0 < effort[0] <= effort[1] <= 160:
            raise ValueError('Bounded positive effort range required')
        if any(type(candidate[k]) is not int or not 1 <= candidate[k] <= 5 for k in ('expected_value', 'risk')):
            raise ValueError('Operator value and risk estimates must be 1..5')
        hashes = {card_map[r]['packet_hash'] for r in refs}
        history = [event for event in feedback if event['target_hash'] in hashes]
        results.append(candidate | {'project': canonical_project_name(candidate['project']),
                       'priority_score': round(candidate['expected_value'] / (candidate['risk'] * effort[1]), 4),
                       'score_basis': 'operator value / (operator risk * upper effort hours); not measured ROI',
                       'prior_feedback_decisions': [event['decision'] for event in sorted(history, key=lambda e: e['reviewed_at'])],
                       'canonical': False, 'review_required': True})
    return sorted(results, key=lambda r: (-r['priority_score'], r['id']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='Private JSON containing packets, cards and optional independence_reviews')
    args = parser.parse_args()
    data = read_json(args.input)
    print(json.dumps(analyze(data['packets'], data['cards'], data.get('independence_reviews', [])), indent=2))


if __name__ == '__main__':
    main()
