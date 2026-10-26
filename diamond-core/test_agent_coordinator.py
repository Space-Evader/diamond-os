"""Execute real fixed workers and check isolation, failure and escalation behavior."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_coordinator import coordinate
from learning_cycle import demo_inputs


@unittest.skipIf(os.environ.get('DIAMOND_WORKER') == '1',
                 'Host integration tests launch workers; recursive dispatch is not permitted')
class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for path in Path(__file__).parent.glob('*.py'):
            shutil.copyfile(path, self.source / path.name)
        self.destination = self.root / 'runs'

    def task(self, role, action, payload):
        return {'id': role, 'role': role, 'action': action, 'payload': payload}

    def run_tasks(self, tasks, timeout=30):
        return coordinate(tasks, self.source, self.destination, timeout)

    def test_all_four_roles_execute_without_editing_source(self):
        plan, selected = demo_inputs()
        file = self.source / 'universe.py'
        original = file.read_bytes()
        tasks = [
            self.task('coding', 'propose_edit', {'path': 'universe.py',
                      'expected_sha256': hashlib.sha256(original).hexdigest(),
                      'before': 'Canonical Diamond Mind Universe taxonomy used by Diamond Core.',
                      'after': 'Taxonomy shared by supervised workers.'}),
            self.task('research', 'extract', {'selected': selected, 'projects': ['Diamond Core'],
                      'reviewed_at': plan['reviewed_at'], 'input_kind': 'synthetic'}),
            self.task('testing', 'unittest', {'pattern': 'test_acceleration_independent.py'}),
            self.task('intelligence', 'cycle', {'plan': plan, 'selected': selected}),
        ]
        summary = self.run_tasks(tasks)
        self.assertEqual([r['state'] for r in summary['tasks']], ['completed'] * 4)
        self.assertEqual(summary['tasks'][2]['result']['tests'], 26)
        self.assertEqual(file.read_bytes(), original)
        self.assertEqual(summary['tasks'][3]['result']['status']['canonical_records'], 0)
        root = Path(summary['run_directory'])
        self.assertTrue((root / 'coding' / 'proposal.patch').is_file())
        self.assertFalse((root / 'research' / 'reviews').exists())

    def test_stale_edit_and_path_traversal_fail_without_repository_write(self):
        for path in ('universe.py', '../universe.py'):
            result = self.run_tasks([self.task('coding', 'propose_edit', {
                'path': path, 'expected_sha256': '0' * 64, 'before': 'unused', 'after': 'unused'})])
            self.assertEqual(result['tasks'][0]['state'], 'failed')

    def test_unsupported_capability_escalates_without_execution(self):
        result = self.run_tasks([self.task('research', 'browse_web', {'url': 'https://example.org'})])
        task = result['tasks'][0]
        self.assertEqual(task['state'], 'needs_specialist')
        self.assertFalse((Path(result['run_directory']) / 'research' / 'result.json').exists())

    def test_unknown_role_duplicate_ids_and_extra_permissions_rejected(self):
        task = self.task('testing', 'unittest', {'pattern': 'test_*.py'})
        for tasks in ([dict(task, role='owner')], [task, task], [dict(task, network=True)]):
            with self.assertRaises(ValueError):
                self.run_tasks(tasks)
        self.assertFalse(self.destination.exists())

    def test_timeout_stops_worker(self):
        (self.source / 'test_blocked.py').write_text(
            'import unittest,time\nclass Blocked(unittest.TestCase):\n'
            ' def test_wait(self): time.sleep(10)\n')
        result = self.run_tasks([self.task('testing', 'unittest', {'pattern': 'test_blocked.py'})], timeout=1)
        self.assertEqual(result['tasks'][0]['state'], 'timed_out')

    def test_failed_prerequisite_blocks_downstream_execution(self):
        first = self.task('testing', 'unsupported_specialist_task', {})
        second = self.task('intelligence', 'cycle', {})
        second['depends_on'] = ['testing']
        result = self.run_tasks([first, second])
        self.assertEqual(result['workers_started'], 0)
        self.assertEqual(result['tasks'][1]['state'], 'blocked_dependency')
        self.assertFalse(result['tasks'][1]['worker_started'])

    def test_forward_or_cyclic_dependencies_rejected_before_writes(self):
        task = self.task('testing', 'unittest', {'pattern': 'test_*.py'})
        task['depends_on'] = ['testing']
        with self.assertRaisesRegex(ValueError, 'preceding'):
            self.run_tasks([task])
        self.assertFalse(self.destination.exists())

    def test_research_handoff_drives_single_source_intelligence(self):
        from test_real_learning import fixture
        from gmail_import import selected_envelope
        selection, metadata, full, plan = fixture()
        research = self.task('research', 'prepare_review', {
            'plan': plan, 'selected': selected_envelope(selection, metadata, full)})
        intelligence = self.task('intelligence', 'review_single', {'from_task': 'research'})
        intelligence['depends_on'] = ['research']
        result = self.run_tasks([research, intelligence])
        self.assertEqual([t['state'] for t in result['tasks']], ['completed', 'completed'])
        self.assertEqual(result['tasks'][1]['result']['status']['current_sources'], 1)
        self.assertEqual(result['tasks'][1]['result']['status']['canonical_records'], 0)
        self.assertNotIn(full['payload']['body']['content'], json.dumps(result))

    def test_testing_worker_executes_proposed_code_in_its_own_snapshot(self):
        original = (self.source / 'universe.py').read_bytes()
        before = 'Canonical Diamond Mind Universe taxonomy used by Diamond Core.'
        after = 'Taxonomy proposed by the bounded coding worker.'
        (self.source / 'test_proposal.py').write_text(
            'import unittest,universe\nclass Proposal(unittest.TestCase):\n'
            ' def test_proposed(self): self.assertIn("Taxonomy proposed by the bounded coding worker.",universe.__doc__)\n')
        coding = self.task('coding', 'propose_edit', {'path': 'universe.py',
            'expected_sha256': hashlib.sha256(original).hexdigest(), 'before': before, 'after': after})
        testing = self.task('testing', 'unittest', {'pattern': 'test_proposal.py', 'proposal_from': 'coding'})
        testing['depends_on'] = ['coding']
        result = self.run_tasks([coding, testing])
        self.assertEqual([t['state'] for t in result['tasks']], ['completed', 'completed'])
        self.assertEqual(result['tasks'][1]['result']['tests'], 1)
        self.assertFalse(result['tasks'][1]['tested_proposal']['applied_to_repository'])
        self.assertEqual((self.source / 'universe.py').read_bytes(), original)

    def test_unapproved_or_tampered_artifact_is_not_dispatched(self):
        from agent_coordinator import resolve_handoff
        run_root = self.root / 'artifacts'
        prior = run_root / 'research'
        prior.mkdir(parents=True)
        (prior / 'handoff.json').write_text('{"schema":"diamond.review-handoff/1","plan":{},"selected":{}}')
        reports = [{'task_id': 'research', 'role': 'research', 'state': 'completed',
                    'result': {'handoff_file': 'handoff.json', 'handoff_hash': '0' * 64}}]
        task = self.task('intelligence', 'review_single', {'from_task': 'research'})
        with self.assertRaisesRegex(ValueError, 'prerequisite'):
            resolve_handoff(task, reports, run_root, self.root, {})
        task['depends_on'] = ['research']
        with self.assertRaisesRegex(ValueError, 'integrity'):
            resolve_handoff(task, reports, run_root, self.root, {})

    def test_failing_tests_are_reported_as_failure(self):
        (self.source / 'test_failure.py').write_text(
            'import unittest\nclass Fails(unittest.TestCase):\n'
            ' def test_fail(self): self.fail("expected")\n')
        result = self.run_tasks([self.task('testing', 'unittest', {'pattern': 'test_failure.py'})])
        report = result['tasks'][0]
        self.assertEqual(report['state'], 'failed')
        self.assertEqual(report['result']['failures'], 1)

    def test_network_and_external_file_reads_blocked_environment_scrubbed(self):
        # Trusted test checks application guards, not hostile-code containment.
        (self.source / 'test_capabilities.py').write_text(
            'import unittest,os,socket\nclass Capabilities(unittest.TestCase):\n'
            ' def test_network(self):\n'
            '  with self.assertRaises(PermissionError): socket.socket()\n'
            ' def test_read(self):\n'
            '  with self.assertRaises(PermissionError): open("/etc/passwd")\n'
            ' def test_secret(self): self.assertNotIn("DIAMOND_TEST_SECRET",os.environ)\n')
        from unittest.mock import patch
        with patch.dict(os.environ, {'DIAMOND_TEST_SECRET': 'not-forwarded'}):
            result = self.run_tasks([self.task('testing', 'unittest', {'pattern': 'test_capabilities.py'})])
        self.assertEqual(result['tasks'][0]['state'], 'completed')
        self.assertEqual(result['tasks'][0]['result']['tests'], 3)


if __name__ == '__main__':
    unittest.main()
