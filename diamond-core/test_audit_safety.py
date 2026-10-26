"""Offline regression checks. All writes go to disposable directories."""
import base64
import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import core_intake as intake
import gmail_review_select as gmail
from discovery_review import prepare, validate_packet, digest
from make_demo import envelope

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / 'discovery_reviews'
        self.enterContext(patch.object(intake, 'STORE', self.store))
        self.enterContext(patch.object(gmail, 'STORE', self.store))
        self.enterContext(patch.object(gmail, 'ROOT', self.root))
        self.sentinels = {}
        for name in ('memory.txt', 'opportunities.json', 'token.json', 'credentials.json'):
            p = self.root / name
            p.write_bytes(b'unchanged synthetic sentinel')
            self.sentinels[p] = p.read_bytes()
        self.addCleanup(self.check_sentinels)

    def check_sentinels(self):
        for p, value in self.sentinels.items():
            self.assertEqual(p.read_bytes(), value)

    def invoke(self, module, args):
        out = io.StringIO()
        with patch('sys.argv', ['test'] + args), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            module.main()
        return out.getvalue()

    def submit(self, e=None):
        path = self.root / 'synthetic.json'
        path.write_text(json.dumps(envelope if e is None else e), encoding='utf-8')
        return self.invoke(intake, ['submit', str(path), '--confirm-review-only'])

    def test_intake_duplicate_retrieval_and_revision(self):
        self.assertIn('SAVED', self.submit())
        first = next(self.store.glob('intake_*.json')).read_bytes()
        self.assertIn('DUPLICATE', self.submit())
        self.assertEqual(len(list(self.store.glob('intake_*.json'))), 1)
        e = copy.deepcopy(envelope)
        e['analysis']['questions'].append('Synthetic revision question?')
        self.assertIn('revision 2', self.submit(e))
        self.assertIn(first, [p.read_bytes() for p in self.store.glob('intake_*.json')])
        self.assertIn('MATCHES: 2', self.invoke(intake, ['search', 'counterargument']))
        self.assertIn('revision=2', self.invoke(intake, ['list']))

    def test_missing_root_rejected(self):
        self.submit()
        e = copy.deepcopy(envelope)
        e['analysis']['questions'].append('Revision two?')
        self.submit(e)
        next(self.store.glob('*r0001.json')).unlink()
        e['analysis']['questions'].append('Revision three?')
        with self.assertRaisesRegex(ValueError, 'history root'):
            self.submit(e)

    def test_rehashed_review_flag_rejected(self):
        p, _ = prepare(**envelope)
        p['review_required'] = False
        p['packet_hash'] = digest({k: v for k, v in p.items() if k != 'packet_hash'})
        with self.assertRaises(ValueError):
            validate_packet(p)

    def test_invalid_revision_rejected(self):
        for value in (0, -1, True, 1.5):
            p, _ = prepare(**envelope)
            p['revision'] = value
            p['packet_hash'] = digest({k:v for k,v in p.items() if k != 'packet_hash'})
            with self.assertRaises(ValueError):
                validate_packet(p)

    def mock_service(self, msg):
        s = MagicMock()
        s.users.return_value.messages.return_value.get.return_value.execute.return_value = msg
        return s

    def message(self, mid='abc123'):
        return {'id': mid, 'payload': {'mimeType': 'text/plain', 'headers': [], 'body': {'data': base64.urlsafe_b64encode(b'Synthetic test message.').decode()}}}

    def select(self, mid='abc123', instruction='synthetic founder selection'):
        return self.invoke(gmail, ['select', '--id', mid, '--confirm-review-only', '--instruction-ref', instruction])

    def test_selected_message_and_no_overwrite(self):
        s = self.mock_service(self.message())
        with patch.object(gmail, 'service', return_value=s):
            self.assertIn('STAGED', self.select())
            target = self.store / 'gmail_selected_abc123.json'
            original = target.read_bytes()
            data = json.loads(original)
            self.assertEqual(data['approval']['scope'], 'review_only')
            self.assertEqual(data['source']['message_id'], 'abc123')
            with self.assertRaises(FileExistsError):
                self.select()
            self.assertEqual(target.read_bytes(), original)
        s.users.return_value.messages.return_value.get.assert_called_with(userId='me', id='abc123', format='full')

    def test_mismatch_and_html_only_rejected(self):
        for msg in (self.message('wrong'), {'id':'abc123', 'payload':{'mimeType':'text/html'}}):
            with patch.object(gmail, 'service', return_value=self.mock_service(msg)):
                with self.assertRaises(ValueError):
                    self.select()
            self.assertFalse(self.store.exists())

    def test_bad_selection_rejected_before_auth(self):
        with patch.object(gmail, 'service') as auth:
            for mid, instruction in (('../outside','ok'), ('abc123',' ')):
                with self.assertRaises(SystemExit):
                    self.select(mid, instruction)
            auth.assert_not_called()

    def test_confirmation_required_before_auth(self):
        with patch.object(gmail, 'service') as auth:
            with self.assertRaises(SystemExit):
                self.invoke(gmail, ['select','--id','abc123','--instruction-ref','test'])
            auth.assert_not_called()

    def test_metadata_listing_only(self):
        s = self.mock_service(self.message())
        s.users.return_value.messages.return_value.list.return_value.execute.return_value = {'messages':[{'id':'abc123'}]}
        with patch.object(gmail, 'service', return_value=s):
            self.invoke(gmail, ['list','--query','synthetic','--limit','1'])
        s.users.return_value.messages.return_value.get.assert_called_once_with(userId='me',id='abc123',format='metadata',metadataHeaders=['From','Subject','Date'])
        self.assertFalse(self.store.exists())

    def test_attachments_omitted(self):
        body = self.message()['payload']
        attached = copy.deepcopy(body)
        attached['filename'] = 'private.txt'
        self.assertEqual(gmail.message_body({'parts':[attached,body]}), 'Synthetic test message.')

    def test_podcast_and_document_accepted(self):
        for kind in ('podcast', 'document'):
            e = copy.deepcopy(envelope)
            e['source']['kind'] = kind
            p, status = prepare(**e)
            self.assertEqual(status, 'new')
            self.assertFalse(p['canonical'])

if __name__ == '__main__':
    unittest.main()
