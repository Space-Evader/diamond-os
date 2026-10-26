"""Focused offline regressions for schema replay and concurrent persistence."""
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import core_intake
import review_store
from discovery_review import digest, prepare, search, validate_packet
from make_demo import envelope


def rehash(packet):
    packet['packet_hash'] = digest({key: value for key, value in packet.items() if key != 'packet_hash'})
    return packet


class StorageHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / 'reviews'

    def test_rehashed_invalid_embedded_analysis_rejected(self):
        original, _ = prepare(**envelope)
        for edit in ('verified_kind', 'verified_label', 'empty_dissent', 'bad_discovery', 'missing_excerpt'):
            p = copy.deepcopy(original)
            if edit == 'verified_kind':
                p['analysis']['ideas'][0]['kind'] = 'verified_knowledge'
            elif edit == 'verified_label':
                p['analysis']['ideas'][0]['evidence_state'] = 'VERIFIED'
            elif edit == 'empty_dissent':
                p['analysis']['dissent'] = []
            elif edit == 'bad_discovery':
                p['analysis']['discovery'] = []
            else:
                p['analysis']['ideas'][0]['excerpt'] = ''
            p['analysis_hash'] = digest(p['analysis'])
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate_packet(rehash(p))

    def test_rehashed_identity_permission_and_hash_mismatches_rejected(self):
        original, _ = prepare(**envelope)
        for edit in ('source', 'permission', 'analysis_hash', 'projects', 'content', 'timestamp', 'missing_field'):
            p = copy.deepcopy(original)
            if edit == 'source':
                p['source']['ref'] += ':other'
                p['permission_record']['source_ref'] = p['source']['ref']
            elif edit == 'permission':
                p['permission_record']['scope'] = 'canonical'
            elif edit == 'analysis_hash':
                p['analysis_hash'] = 'f' * 64
            elif edit == 'projects':
                p['projects'] = ['HatsRx']
            elif edit == 'content':
                p['source']['content'] = 'private body must not be embedded'
            elif edit == 'timestamp':
                p['reviewed_at'] = None
            else:
                del p['previous_packet_hash']
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate_packet(rehash(p))

    def test_malformed_idea_types_fail_with_value_error(self):
        for key in ('kind', 'evidence_state'):
            e = copy.deepcopy(envelope)
            e['analysis']['ideas'][0][key] = []
            with self.assertRaises(ValueError):
                prepare(**e)

    def test_email_ref_id_must_agree(self):
        e = copy.deepcopy(envelope)
        e['source'].update(kind='email', message_id='abc123', ref='gmail:message:other')
        e['approval']['source_ref'] = e['source']['ref']
        with self.assertRaisesRegex(ValueError, 'match selected'):
            prepare(**e)

    def test_metadata_and_permission_changes_are_revisions(self):
        p, _ = prepare(**envelope)
        for field, target in (('title', 'source'), ('instruction_ref', 'approval')):
            e = copy.deepcopy(envelope)
            e[target][field] += ' amended'
            new, status = prepare(**e, previous=p)
            self.assertEqual((new['revision'], status), (2, 'new_revision'))
            self.assertEqual(new['previous_packet_hash'], p['packet_hash'])

    def test_nested_source_metadata_is_detached(self):
        e = copy.deepcopy(envelope)
        e['source']['provenance'] = {'locators': ['paragraph 1']}
        p, _ = prepare(**e)
        e['source']['provenance']['locators'].append('modified input')
        self.assertEqual(p['source']['provenance']['locators'], ['paragraph 1'])
        validate_packet(p)

    def test_atomic_failure_leaves_no_partial_record(self):
        self.store.mkdir()
        with patch.object(review_store.os, 'link', side_effect=OSError('simulated publication failure')):
            with self.assertRaises(OSError):
                review_store.atomic_json_create(self.store / 'intake_test.json', {'packet': 'complete'})
        self.assertEqual(list(self.store.iterdir()), [])

    def test_atomic_publication_does_not_replace(self):
        self.store.mkdir()
        target = self.store / 'intake_test.json'
        target.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            review_store.atomic_json_create(target, {'packet': 'replacement'})
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(list(self.store.iterdir()), [target])

    def test_concurrent_duplicate_append_is_idempotent(self):
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(lambda _: core_intake.submit_envelope(envelope, self.store), range(6)))
        self.assertEqual([status for _, status, _ in results].count('new'), 1)
        self.assertEqual([status for _, status, _ in results].count('duplicate'), 5)
        self.assertEqual(len(core_intake.packets(self.store)), 1)

    def test_concurrent_distinct_revisions_form_one_chain(self):
        core_intake.submit_envelope(envelope, self.store)
        envelopes = []
        for index in range(5):
            e = copy.deepcopy(envelope)
            e['analysis']['questions'].append(f'Synthetic concurrent question {index}?')
            envelopes.append(e)
        with ThreadPoolExecutor(max_workers=5) as workers:
            results = list(workers.map(lambda e: core_intake.submit_envelope(e, self.store), envelopes))
        self.assertEqual(sorted(p['revision'] for p, _, _ in results), [2, 3, 4, 5, 6])
        self.assertEqual(len(core_intake.packets(self.store)), 6)

    def test_retrieval_rejects_incomplete_and_broken_chains(self):
        first, _, root = core_intake.submit_envelope(envelope, self.store)
        e = copy.deepcopy(envelope)
        e['analysis']['questions'].append('Second revision?')
        second, _, tail = core_intake.submit_envelope(e, self.store)
        wrapper = json.loads(tail.read_text())
        wrapper['packet']['previous_packet_hash'] = 'f' * 64
        wrapper['packet'] = rehash(wrapper['packet'])
        tail.write_text(json.dumps(wrapper))
        with self.assertRaisesRegex(ValueError, 'Broken revision history'):
            core_intake.packets(self.store)
        with self.assertRaisesRegex(ValueError, 'history root'):
            search([second], 'discovery')
        root.unlink()
        with self.assertRaisesRegex(ValueError, 'history root'):
            core_intake.packets(self.store)

    def test_stale_lock_fails_closed(self):
        self.store.mkdir()
        lock = self.store / '.intake.lock'
        lock.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'locked'):
            with review_store.store_lock(self.store, timeout=0):
                self.fail('Must not acquire an existing lock')
        self.assertTrue(lock.is_dir())
        self.assertFalse(list(self.store.glob('intake_*.json')))


if __name__ == '__main__':
    unittest.main()
