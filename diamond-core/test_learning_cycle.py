"""Cycle integration, restart behavior and review/credential boundaries."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from learning_cycle import (demo_inputs, private_directory, read_json, run_cycle,
                            select_message)
from learning_pipeline import read_state


class LearningCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / 'reviews'
        self.plan, self.inputs = demo_inputs()

    def test_complete_cycle_and_replay_do_not_duplicate_records(self):
        first = run_cycle(self.plan, self.inputs, self.store)
        self.assertEqual([r['result'] for r in first['ingests']], ['new', 'new'])
        self.assertTrue(all(r['replay'] == 'duplicate' for r in first['ingests']))
        second = run_cycle(self.plan, self.inputs, self.store)
        self.assertTrue(second['repeated_cycle'])
        self.assertEqual(first['connection_hash'], second['connection_hash'])
        self.assertEqual(second['status']['packet_revisions'], 2)
        self.assertEqual(second['status']['connections'], 1)
        self.assertEqual(second['status']['feedback_events'], 1)
        for record in sum((list(records) for records in read_state(self.store)), []):
            self.assertIs(record['canonical'], False)
            self.assertIs(record['review_required'], True)

    def test_resume_after_feedback_failure_reuses_published_records(self):
        with patch('learning_cycle.record_feedback', side_effect=RuntimeError('interruption')):
            with self.assertRaises(RuntimeError):
                run_cycle(self.plan, self.inputs, self.store)
        result = run_cycle(self.plan, self.inputs, self.store)
        self.assertTrue(result['repeated_cycle'])
        self.assertEqual(result['status']['connections'], 1)
        self.assertEqual(result['status']['feedback_events'], 1)

    def test_replaying_old_cycle_does_not_revert_new_source_revision(self):
        run_cycle(self.plan, self.inputs, self.store)
        newer = copy.deepcopy(self.inputs)
        newer[0]['source']['content'] += ' Later evidence challenges the original claim and requires a revised interpretation.'
        run_cycle(self.plan, newer, self.store)
        before = read_state(self.store)
        replay = run_cycle(self.plan, self.inputs, self.store)
        self.assertTrue(replay['receipt_replayed'])
        self.assertEqual(before, read_state(self.store))
        self.assertEqual(replay['status']['packet_revisions'], 3)

    def test_invalid_second_source_does_not_stage_first(self):
        self.inputs[1]['source']['ref'] = 'https://attacker.example/not-approved/'
        with self.assertRaises(ValueError):
            run_cycle(self.plan, self.inputs, self.store)
        self.assertFalse(self.store.exists())

    def test_disabled_source_rejected_without_state(self):
        self.inputs[1]['source'].update(kind='email', source_id='the-signal', message_id='abc',
                                        account_ref='test', creator='Unknown <unknown@example.org>')
        with self.assertRaises(ValueError):
            run_cycle(self.plan, self.inputs, self.store)
        self.assertFalse(self.store.exists())

    def test_identical_bodies_cannot_be_claimed_as_independent_support(self):
        self.inputs[1]['source']['content'] = self.inputs[0]['source']['content']
        self.plan['synthesis']['relation'] = 'support'
        with self.assertRaisesRegex(ValueError, 'lineages'):
            run_cycle(self.plan, self.inputs, self.store)
        self.assertFalse(self.store.exists())

    def test_duplicate_source_references_rejected(self):
        with self.assertRaisesRegex(ValueError, 'distinct'):
            run_cycle(self.plan, [self.inputs[0], self.inputs[0]], self.store)

    def test_missing_feedback_or_promotion_field_rejected(self):
        for change in ('missing_feedback', 'promote'):
            plan = copy.deepcopy(self.plan)
            if change == 'missing_feedback':
                del plan['feedback']
            else:
                plan['canonical'] = True
            with self.assertRaises(ValueError):
                run_cycle(plan, self.inputs, self.store)
        self.assertFalse(self.store.exists())

    def test_real_declaration_is_never_claim_verification(self):
        self.plan['input_kind'] = 'real'
        result = run_cycle(self.plan, self.inputs, self.store)
        self.assertEqual(result['input_kind'], 'real')
        self.assertIn('not independently verified', result['input_provenance'])
        self.assertFalse(result['canonical'])

    def test_report_omits_selected_source_bodies(self):
        report = run_cycle(self.plan, self.inputs, self.store)
        serialized = json.dumps(report)
        for selected in self.inputs:
            self.assertNotIn(selected['source']['content'], serialized)
        self.assertEqual(len(list((self.store / 'cycles').glob('*.json'))), 1)

    def test_private_state_rejects_git_checkout_and_symlinks(self):
        checkout = self.root / 'checkout'
        (checkout / '.git').mkdir(parents=True)
        (checkout / '.git' / 'HEAD').write_text('ref: refs/heads/test')
        with self.assertRaisesRegex(ValueError, 'Git checkout'):
            private_directory(checkout / 'reviews')
        target = self.root / 'target'
        target.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symbolic'):
            private_directory(alias / 'reviews')

    @unittest.skipUnless(os.name == 'posix', 'POSIX mode checks')
    def test_private_state_rejects_group_readable_directory(self):
        self.store.mkdir(mode=0o755)
        self.store.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'user-only'):
            private_directory(self.store)

    def test_bounded_input_reader(self):
        source = self.root / 'data.json'
        source.write_text('{}')
        alias = self.root / 'alias.json'
        alias.symlink_to(source)
        with self.assertRaises(ValueError):
            read_json(alias)
        with patch('learning_cycle.MAX_BYTES', 1):
            with self.assertRaises(ValueError):
                read_json(source)

    def test_selector_uses_external_store_without_interactive_login(self):
        token_dir = self.root / 'oauth'
        token_dir.mkdir(mode=0o700)
        token = token_dir / 'authorized.json'
        token.write_text('{}')
        token.chmod(0o600)
        import gmail_review_select as selector

        def staged(args):
            self.assertEqual(selector.STORE, self.store)
            self.assertEqual(args.id, 'exact123')
            self.assertTrue(args.confirm_review_only)
        with patch.object(selector, 'select_approved', side_effect=staged) as selected:
            path = select_message('nautilus', 'exact123', 'stable-label', 'explicit request',
                                  self.store, token)
            selected.assert_called_once()
        self.assertEqual(path.parent, self.store)
        self.assertNotIn('stable-label', path.name)

    def test_selector_rejects_repo_token_before_loading_credentials(self):
        with self.assertRaises(ValueError):
            select_message('nautilus', 'abc', 'account', 'instruction', self.store,
                           Path(__file__).parent / 'token.json')


if __name__ == '__main__':
    unittest.main()
