"""Offline approved-source Gmail regression checks; no credentials or network."""
import base64
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import gmail_review_select as gmail
from source_policy import account_message_ref


class ApprovedGmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / 'reviews'
        self.enterContext(patch.object(gmail, 'STORE', self.store))

    def message(self, sender='Superhuman <superhuman@mail.joinsuperhuman.ai>', mid='abc123'):
        return {'id': mid, 'payload': {
            'mimeType': 'text/plain',
            'headers': [{'name': 'From', 'value': sender},
                        {'name': 'Subject', 'value': 'Synthetic newsletter'},
                        {'name': 'Date', 'value': 'Sun, 25 Oct 2026 12:00:00 +0000'}],
            'body': {'data': base64.urlsafe_b64encode(b'Private synthetic newsletter body.').decode()}}}

    def client(self, metadata=None, full=None):
        metadata = self.message() if metadata is None else metadata
        full = self.message() if full is None else full
        client = MagicMock()
        client.users.return_value.messages.return_value.get.return_value.execute.side_effect = [metadata, full]
        return client

    def invoke(self, source='superhuman', account='synthetic-account', instruction='synthetic authorization'):
        output = io.StringIO()
        args = ['gmail', 'select-approved', '--source', source, '--id', 'abc123',
                '--account-ref', account, '--confirm-review-only', '--instruction-ref', instruction]
        with patch('sys.argv', args), contextlib.redirect_stdout(output):
            gmail.main()
        return output.getvalue()

    def test_exact_sender_stages_account_scoped_private_envelope(self):
        client = self.client()
        with patch.object(gmail, 'service', return_value=client):
            output = self.invoke()
        files = list(self.store.glob('gmail_approved_*.json'))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text())
        source = data['source']
        self.assertEqual(source['ref'], account_message_ref('synthetic-account', 'abc123'))
        self.assertEqual(source['source_id'], 'superhuman')
        self.assertEqual(source['published_at'], '2026-10-25T12:00:00+00:00')
        self.assertEqual(data['approval']['scope'], 'review_only')
        self.assertNotIn('Private synthetic newsletter body.', output)
        self.assertNotIn('synthetic-account', files[0].name)
        self.assertIn('STAGED', output)
        calls = client.users.return_value.messages.return_value.get.call_args_list
        self.assertEqual(calls[0].kwargs['format'], 'metadata')
        self.assertEqual(calls[1].kwargs['format'], 'full')
        if os.name == 'posix':
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)

    def test_sender_case_normalization(self):
        msg = self.message('SUPERHUMAN@MAIL.JOINSUPERHUMAN.AI')
        with patch.object(gmail, 'service', return_value=self.client(msg, msg)):
            self.assertIn('STAGED', self.invoke())

    def test_metadata_spoof_rejected_before_full_fetch(self):
        msg = self.message('Superhuman <attacker@example.org>')
        client = self.client(msg)
        with patch.object(gmail, 'service', return_value=client):
            with self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(client.users.return_value.messages.return_value.get.call_count, 1)
        self.assertFalse(self.store.exists())

    def test_wrong_mailbox_on_approved_domain_rejected(self):
        client = self.client(self.message('wrong@mail.joinsuperhuman.ai'))
        with patch.object(gmail, 'service', return_value=client):
            with self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(client.users.return_value.messages.return_value.get.call_count, 1)

    def test_duplicate_from_metadata_rejected_before_full_fetch(self):
        msg = self.message()
        msg['payload']['headers'].append({'name': 'fRoM', 'value': 'attacker@example.org'})
        client = self.client(msg)
        with patch.object(gmail, 'service', return_value=client):
            with self.assertRaisesRegex(ValueError, 'one From'):
                self.invoke()
        self.assertEqual(client.users.return_value.messages.return_value.get.call_count, 1)

    def test_missing_from_rejected(self):
        msg = self.message()
        msg['payload']['headers'] = []
        with patch.object(gmail, 'service', return_value=self.client(msg)):
            with self.assertRaisesRegex(ValueError, 'one From'):
                self.invoke()

    def test_full_message_sender_is_reverified(self):
        client = self.client(full=self.message('Superhuman <attacker@example.org>'))
        with patch.object(gmail, 'service', return_value=client):
            with self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(client.users.return_value.messages.return_value.get.call_count, 2)
        self.assertFalse(self.store.exists())

    def test_full_duplicate_from_rejected(self):
        msg = self.message()
        msg['payload']['headers'].append(copy.deepcopy(msg['payload']['headers'][0]))
        with patch.object(gmail, 'service', return_value=self.client(full=msg)):
            with self.assertRaisesRegex(ValueError, 'one From'):
                self.invoke()
        self.assertFalse(self.store.exists())

    def test_message_id_verified_at_both_retrievals(self):
        for stage in ('metadata', 'full'):
            with self.subTest(stage=stage):
                client = self.client(**{stage: self.message(mid='wrong')})
                with patch.object(gmail, 'service', return_value=client):
                    with self.assertRaisesRegex(ValueError, 'message ID'):
                        self.invoke()
                expected = 1 if stage == 'metadata' else 2
                self.assertEqual(client.users.return_value.messages.return_value.get.call_count, expected)
                self.assertFalse(self.store.exists())

    def test_disabled_and_unknown_sources_rejected_before_auth(self):
        for source in ('unknown', 'the-signal', 'diary-of-a-ceo'):
            with self.subTest(source=source), patch.object(gmail, 'service') as authenticate:
                with self.assertRaises(ValueError):
                    self.invoke(source=source)
                authenticate.assert_not_called()

    def test_empty_account_rejected_before_auth(self):
        with patch.object(gmail, 'service') as authenticate:
            with self.assertRaises(ValueError):
                self.invoke(account=' ')
            authenticate.assert_not_called()

    def test_empty_instruction_rejected_before_auth(self):
        with patch.object(gmail, 'service') as authenticate, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.invoke(instruction=' ')
            authenticate.assert_not_called()

    def test_accounts_have_separate_filenames_and_no_overwrite(self):
        for account in ('first-account', 'second-account'):
            with patch.object(gmail, 'service', return_value=self.client()):
                self.invoke(account=account)
        files = list(self.store.glob('gmail_approved_*.json'))
        self.assertEqual(len(files), 2)
        originals = {path: path.read_bytes() for path in files}
        with patch.object(gmail, 'service', return_value=self.client()):
            with self.assertRaises(FileExistsError):
                self.invoke(account='first-account')
        self.assertEqual({path: path.read_bytes() for path in files}, originals)

    def test_html_only_message_rejected(self):
        msg = self.message()
        msg['payload']['mimeType'] = 'text/html'
        with patch.object(gmail, 'service', return_value=self.client(full=msg)):
            with self.assertRaisesRegex(ValueError, 'No plain-text body'):
                self.invoke()
        self.assertFalse(self.store.exists())

    def test_nullable_mime_parts_and_body_from_connector(self):
        msg = self.message()
        msg['payload']['parts'] = None
        self.assertEqual(gmail.message_body(msg['payload']), 'Private synthetic newsletter body.')
        self.assertEqual(gmail.message_body({'mimeType': 'text/plain', 'body': None, 'parts': None}), '')

    def test_connector_plaintext_and_attachment_identity(self):
        part = {'mime_type': 'text/plain', 'parts': None, 'body': {'content': 'Synthetic connector content.'}}
        self.assertEqual(gmail.message_body(part), 'Synthetic connector content.')
        part['body']['attachment_id'] = 'synthetic-attachment'
        self.assertEqual(gmail.message_body(part), '')

    def test_missing_or_timezone_free_publication_date_is_unknown(self):
        self.assertIsNone(gmail.published_timestamp(None))
        self.assertIsNone(gmail.published_timestamp('invalid'))
        self.assertIsNone(gmail.published_timestamp('Sun, 25 Oct 2026 12:00:00'))


if __name__ == '__main__':
    unittest.main()
