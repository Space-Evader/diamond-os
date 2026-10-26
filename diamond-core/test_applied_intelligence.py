"""Grounding, independent-support boundaries, ranking and behavioral regressions."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from discovery_review import prepare
from evidence_relations import analyze, rank_candidates
from learning_cycle import prepare_single_review
from test_real_learning import fixture
from gmail_import import selected_envelope


class EvidenceRelationsTests(unittest.TestCase):
    def setUp(self):
        selection, metadata, full, plan = fixture()
        envelope = prepare_single_review(plan, selected_envelope(selection, metadata, full))
        packet, _ = prepare(**envelope)
        self.packets = [packet]
        self.card = {'id': 'a', 'packet_hash': packet['packet_hash'], 'idea_index': 0,
                     'story_key': 'one-story', 'claim_key': 'one-claim', 'stance': 'supports'}

    def test_repeated_story_is_not_independent_evidence(self):
        result = analyze(self.packets, [self.card, self.card | {'id': 'b'}])
        self.assertEqual(result['repeated_stories'][0]['distinct_sources'], 1)
        self.assertEqual(len(result['repeated_excerpt_groups']), 1)
        self.assertEqual(result['independence_status'], 'not_established')

    def test_opposing_reported_positions_are_not_adjudicated(self):
        result = analyze(self.packets, [self.card, self.card | {'id': 'b', 'stance': 'disputes'}])
        self.assertEqual(result['conflicting_claims'][0]['classification'], 'reported_dispute_not_adjudicated')
        self.assertFalse(result['canonical'])

    def test_unknown_or_stale_evidence_rejected(self):
        for invalid in (self.card | {'packet_hash': '0' * 64}, self.card | {'idea_index': 99}):
            with self.assertRaises(ValueError):
                analyze(self.packets, [invalid])

    def test_duplicate_lineage_cannot_be_reviewed_as_independent(self):
        cards = [self.card, self.card | {'id': 'b'}]
        review = {'cards': ['a', 'b'], 'publisher_groups': ['one', 'two'],
                  'origin_refs': ['origin1', 'origin2'], 'reviewer': 'Reviewer', 'rationale': 'Claimed independence'}
        with self.assertRaisesRegex(ValueError, 'distinct lineages'):
            analyze(self.packets, cards, [review])

    def test_independent_support_needs_review_and_does_not_verify_claim(self):
        # Produce a genuine second grounded packet instead of changing stored hashes.
        selection, metadata, full, plan = fixture()
        selection['source_id'] = 'superhuman'
        metadata['payload']['headers'][0]['value'] = 'Superhuman <superhuman@mail.joinsuperhuman.ai>'
        full['payload']['headers'][0]['value'] = 'Superhuman <superhuman@mail.joinsuperhuman.ai>'
        selection['message_id'] = metadata['id'] = full['id'] = 'second123'
        full['payload']['body']['content'] += ' Additional independently supplied context.'
        old = 'distinguish an article teaser from the actual evidence'
        new = 'separate the promotional summary from the underlying evidence'
        full['payload']['body']['content'] = full['payload']['body']['content'].replace(old, new)
        start = full['payload']['body']['content'].index(new)
        plan['evidence_spans'] = [{'start': start, 'end': start + len(new)}]
        envelope = prepare_single_review(plan, selected_envelope(selection, metadata, full))
        other, _ = prepare(**envelope)
        cards = [self.card, self.card | {'id': 'b', 'packet_hash': other['packet_hash']}]
        review = {'cards': ['a', 'b'], 'publisher_groups': ['nautilus', 'superhuman-network'],
                  'origin_refs': ['origin1', 'origin2'], 'reviewer': 'Reviewer', 'rationale': 'Synthetic independence assessment'}
        result = analyze(self.packets + [other], cards, [review])
        self.assertFalse(result['reviewed_independent_support'][0]['claim_verified'])

    def test_verbatim_excerpt_is_not_independent_despite_different_newsletter_bodies(self):
        selection, metadata, full, plan = fixture()
        selection['source_id'] = 'superhuman'
        selection['message_id'] = metadata['id'] = full['id'] = 'second123'
        metadata['payload']['headers'][0]['value'] = full['payload']['headers'][0]['value'] = 'Superhuman <superhuman@mail.joinsuperhuman.ai>'
        full['payload']['body']['content'] += ' Different newsletter wrapper.'
        other, _ = prepare(**prepare_single_review(plan, selected_envelope(selection, metadata, full)))
        cards = [self.card, self.card | {'id': 'b', 'packet_hash': other['packet_hash']}]
        review = {'cards': ['a', 'b'], 'publisher_groups': ['nautilus', 'superhuman-network'],
                  'origin_refs': ['origin1', 'origin2'], 'reviewer': 'Reviewer', 'rationale': 'Claimed independence'}
        with self.assertRaisesRegex(ValueError, 'Repeated reporting'):
            analyze(self.packets + [other], cards, [review])

    def test_ranking_uses_explicit_effort_and_retains_outcomes(self):
        candidate = {'id': 'small', 'project': 'Diamond Core', 'hypothesis': 'Try a small gate',
                     'evidence_cards': ['a'], 'uncertainty': 'No measured benefit yet',
                     'effort_hours': [1, 2], 'expected_value': 4, 'risk': 1}
        other = candidate | {'id': 'large', 'project': 'HatsRx', 'effort_hours': [4, 8]}
        feedback = [{'target_hash': self.card['packet_hash'], 'decision': 'useful', 'reviewed_at': '2026-10-26T12:00:00+00:00'}]
        ranked = rank_candidates([other, candidate], [self.card], self.packets, feedback)
        self.assertEqual(ranked[0]['id'], 'small')
        self.assertEqual(ranked[0]['prior_feedback_decisions'], ['useful'])
        self.assertFalse(ranked[0]['canonical'])
        with self.assertRaises(ValueError):
            rank_candidates([candidate | {'evidence_cards': ['unknown']}], [self.card], self.packets)


@unittest.skipIf(os.environ.get('DIAMOND_WORKER') == '1', 'Host test dispatches workers')
class BehaviorGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for file in Path(__file__).parent.glob('*.py'):
            shutil.copyfile(file, self.source / file.name)

    def task(self, action, payload):
        return {'id': 'verify', 'role': 'testing', 'action': action, 'payload': payload}

    def run_task(self, task):
        from agent_coordinator import coordinate
        return coordinate([task], self.source, self.root / 'runs')

    def test_actual_cli_and_stored_receipts_are_verified(self):
        result = self.run_task(self.task('verify_cycle_cli', {}))
        report = result['tasks'][0]
        self.assertEqual(report['state'], 'completed')
        self.assertEqual(report['result']['executions'], 2)
        self.assertEqual(report['result']['canonical_records'], 0)
        self.assertTrue((Path(result['run_directory']) / 'verify' / 'behavior-proof.json').is_file())

    def test_gate_catches_cli_regression_that_function_tests_miss(self):
        source = self.source / 'learning_cycle.py'
        original = source.read_text()
        before = 'result = run_cycle(plan, inputs, args.store)'
        self.assertEqual(original.count(before), 1)
        source.write_text(original.replace(before, 'result = {"pretend": "success"}'))
        unit = self.run_task(self.task('unittest', {'pattern': 'test_learning_cycle.py'}))
        self.assertEqual(unit['tasks'][0]['state'], 'completed')
        self.assertEqual(unit['tasks'][0]['result']['tests'], 15)
        behavior = self.run_task(self.task('verify_cycle_cli', {}))
        self.assertEqual(behavior['tasks'][0]['state'], 'failed')
        self.assertFalse((Path(behavior['run_directory']) / 'verify' / 'behavior-proof.json').exists())


if __name__ == '__main__':
    unittest.main()
