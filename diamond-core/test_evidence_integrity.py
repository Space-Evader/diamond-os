"""Synthetic MIME and exact-selection regressions; no mailbox or network access."""
import base64
import copy
import tempfile
import unittest
from pathlib import Path

from discovery_review import digest
from gmail_import import import_message, selected_envelope
from gmail_review_select import message_body
from learning_cycle import prepare_single_review, run_single_review
from learning_pipeline import read_state
from test_real_learning import fixture


def part(raw, charset='utf-8'):
    return {'mimeType': 'text/plain', 'headers': [
        {'name': 'Content-Type', 'value': 'text/plain; charset=' + charset}],
        'body': {'data': base64.urlsafe_b64encode(raw).decode().rstrip('=')}}


class MimeIntegrityTests(unittest.TestCase):
    def test_latin1_and_utf8_preserve_characters(self):
        for charset in ('iso-8859-1', 'utf-8'):
            with self.subTest(charset=charset):
                self.assertEqual(message_body(part('Café'.encode(charset), charset)), 'Café')

    def test_multipart_uses_each_parts_charset_and_skips_attachments(self):
        attached = part(b'private attachment')
        attached['filename'] = 'attachment.txt'
        payload = {'mimeType': 'multipart/mixed', 'parts': [
            part(b'Caf\xe9', 'iso-8859-1'), {'mimeType': 'multipart/alternative',
            'parts': [part('Świątek'.encode()), {'mimeType': 'text/html',
            'body': {'data': 'ignored'}}]}, attached]}
        self.assertEqual(message_body(payload), 'Café\nŚwiątek')

    def test_absent_charset_uses_strict_utf8(self):
        payload = part('Café'.encode())
        payload['headers'] = []
        self.assertEqual(message_body(payload), 'Café')
        payload['body']['data'] = base64.urlsafe_b64encode(b'Caf\xe9').decode()
        with self.assertRaisesRegex(ValueError, 'encoding'):
            message_body(payload)

    def test_malformed_unsupported_and_invalid_bytes_rejected(self):
        for charset, raw in [('unknown-charset', b'Caf\xe9'), ('', b'abc'),
                             ('"utf-8', b'abc'), ('utf-8', b'Caf\xe9'),
                             ('utf-8; charset=latin1', b'abc')]:
            with self.subTest(charset=charset), self.assertRaises(ValueError):
                message_body(part(raw, charset))
        payload = part(b'abc')
        payload['body']['data'] = '%%%'
        with self.assertRaises(ValueError):
            message_body(payload)

    def test_invalid_part_rejects_whole_message_before_storage(self):
        selection, metadata, message, _ = fixture()
        message['payload'].update(mime_type='multipart/mixed', body={},
            parts=[part(b'Valid body'), part(b'Caf\xe9', 'utf-8')])
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'staged'
            with self.assertRaises(ValueError):
                import_message(selection, metadata, message, store)
            self.assertFalse(store.exists())

    def test_latin1_import_preserves_provenance_hash_and_dedup(self):
        selection, metadata, message, plan = fixture()
        text = 'Café: The study found a measurable effect.'
        mime = part(text.encode('latin1'), 'iso-8859-1')
        mime['headers'] += message['payload']['headers']
        message['payload'].pop('mime_type')
        message['payload'].update(mime)
        selected = selected_envelope(selection, metadata, message)
        self.assertEqual(selected['source']['content'], text)
        self.assertEqual(selected['source']['capture_provenance']['transport'], 'operator_export')
        plan['evidence_spans'] = [{'start': 0, 'end': len(text)}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, result = import_message(selection, metadata, message, root / 'import')
            self.assertEqual(result, 'staged')
            self.assertEqual(import_message(selection, metadata, message, path.parent)[1], 'duplicate')
            run_single_review(plan, selected, root / 'reviews')
            packet = read_state(root / 'reviews')[0][0]
            self.assertEqual(packet['content_hash'], digest(text))
            self.assertEqual(packet['analysis']['ideas'][0]['excerpt'], text)


class ExplicitSelectionTests(unittest.TestCase):
    def setUp(self):
        selection, metadata, message, self.plan = fixture()
        self.text = 'The study found a measurable effect.'
        message['payload']['body']['content'] = self.text
        self.selected = selected_envelope(selection, metadata, message)
        self.plan['evidence_spans'] = [{'start': 0, 'end': len(self.text)}]

    def test_short_explicit_sentence_stores_and_replays_review_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'reviews'
            report = run_single_review(self.plan, self.selected, store)
            self.assertTrue(run_single_review(self.plan, self.selected, store)['receipt_replayed'])
            self.assertEqual(report['duplicate_replay'], 'duplicate')
            packets, _, feedback = read_state(store)
            self.assertEqual(len(packets), 1)
            self.assertEqual(len(feedback), 1)
            self.assertEqual(packets[0]['content_hash'], digest(self.text))
            self.assertEqual(packets[0]['analysis']['ideas'][0]['excerpt'], self.text)
            self.assertFalse(packets[0]['canonical'])
            self.assertTrue(packets[0]['review_required'])

    def test_fabricated_altered_and_invalid_selections_rejected_before_writes(self):
        invalid = [[{'start': -1, 'end': 5}], [{'start': 0, 'end': 999}],
                   [{'start': 0, 'end': 0}], [{'start': False, 'end': 5}],
                   [{'start': 0, 'end': 5, 'excerpt': 'Invented evidence'}],
                   [{'start': 0, 'end': 5}, {'start': 2, 'end': 8}],
                   [{'start': '0', 'end': 5}], []]
        for spans in invalid:
            with self.subTest(spans=spans), tempfile.TemporaryDirectory() as directory:
                plan = copy.deepcopy(self.plan)
                plan['evidence_spans'] = spans
                store = Path(directory) / 'reviews'
                with self.assertRaises(ValueError):
                    run_single_review(plan, self.selected, store)
                self.assertFalse(store.exists())

    def test_explicit_selection_cannot_bypass_source_or_canonical_validation(self):
        for defect in ('source', 'approval', 'canonical'):
            selected, plan = copy.deepcopy(self.selected), copy.deepcopy(self.plan)
            if defect == 'source':
                selected['source']['creator'] = 'Attacker <unknown@example.org>'
            elif defect == 'approval':
                selected['approval']['scope'] = 'canonical'
            else:
                plan['canonical'] = True
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                prepare_single_review(plan, selected)


if __name__ == '__main__':
    unittest.main()
