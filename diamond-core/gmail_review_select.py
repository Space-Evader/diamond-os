"""Isolated Gmail read-only message selector for supervised Diamond Core discovery.

No imports from dmio_gmail, no intelligence sweep, no canonical writes.
OAuth may update token.json when Google credentials need refreshing.
"""
import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
STORE = ROOT / 'discovery_reviews'


def service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    token = ROOT / 'token.json'
    credentials = ROOT / 'credentials.json'
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials.exists():
                raise FileNotFoundError('credentials.json not found; no Gmail connection attempted')
            creds = InstalledAppFlow.from_client_secrets_file(str(credentials), SCOPES).run_local_server(port=0)
        token.write_text(creds.to_json(), encoding='utf-8')
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def header_map(payload):
    return {h.get('name', '').lower(): h.get('value', '') for h in payload.get('headers', [])}


def message_body(payload):
    """Extract text/plain only, never attachments; no HTML-to-text inference."""
    results = []
    def visit(part):
        body = part.get('body') or {}
        if part.get('filename') or body.get('attachmentId') or body.get('attachment_id'):
            return
        mime = part.get('mimeType') or part.get('mime_type', '')
        if mime == 'text/plain':
            text_content = body.get('content')
            data = body.get('data') or body.get('base64_url_content')
            if isinstance(text_content, str) and text_content:
                results.append(text_content)
            elif data:
                raw = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
                results.append(raw.decode('utf-8', errors='replace'))
        for child in part.get('parts') or []:
            visit(child)
    visit(payload)
    return '\n'.join(results).strip()


def verified_headers(message, message_id, source_id):
    """Check the selected identity before reading its body or trusting metadata."""
    from source_policy import match_sender
    if not isinstance(message, dict) or message.get('id') != message_id:
        raise ValueError('Returned message ID does not match selected ID')
    payload = message.get('payload', {})
    senders = [h.get('value') for h in payload.get('headers', [])
               if h.get('name', '').casefold() == 'from']
    if len(senders) != 1:
        raise ValueError('Exactly one From header is required')
    match_sender(senders[0], source_id)
    return payload, header_map(payload)


def published_timestamp(value):
    """Preserve a parseable publication date; missing timezone remains unknown."""
    try:
        stamp = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return stamp.isoformat() if stamp.tzinfo is not None else None


def select_approved(args):
    """Stage one approved-source message, verifying metadata before full retrieval."""
    from source_policy import account_message_ref, policy
    from discovery_review import validate_source
    from review_store import atomic_json_create
    selected = policy(args.source)
    if not selected['email_enabled']:
        raise ValueError('Email source identity has not been verified')
    ref = account_message_ref(args.account_ref, args.id)
    gmail = service()
    messages = gmail.users().messages()
    metadata = messages.get(userId='me', id=args.id, format='metadata',
                            metadataHeaders=['From', 'Subject', 'Date']).execute()
    verified_headers(metadata, args.id, args.source)
    message = messages.get(userId='me', id=args.id, format='full').execute()
    payload, headers = verified_headers(message, args.id, args.source)
    content = message_body(payload)
    if not content:
        raise ValueError('No plain-text body available; no file written')
    source = {
        'kind': 'email', 'ref': ref, 'message_id': args.id,
        'account_ref': args.account_ref, 'source_id': args.source,
        'title': headers.get('subject') or '(No subject)',
        'creator': headers['from'],
        'published_at': published_timestamp(headers.get('date')),
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'access_basis': 'Founder selected an exact approved-source Gmail message for review-only local staging',
        'content': content,
    }
    approval = {'source_ref': ref, 'scope': 'review_only',
                'instruction_ref': args.instruction_ref}
    validate_source(source, approval)
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STORE / ('gmail_approved_' + hashlib.sha256(ref.encode('utf-8')).hexdigest() + '.json')
    atomic_json_create(path, {'source': source, 'approval': approval})
    print('STAGED:', path.name)
    print('Contains private email content. No analysis or canonical writes performed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    ls = sub.add_parser('list', help='Read Gmail message metadata only')
    ls.add_argument('--query', required=True, help='Gmail search query')
    ls.add_argument('--limit', type=int, default=10)
    sel = sub.add_parser('select', help='Stage one exact message for founder-approved review')
    sel.add_argument('--id', required=True, help='Exact Gmail message ID from list')
    sel.add_argument('--confirm-review-only', action='store_true', required=True)
    sel.add_argument('--instruction-ref', required=True, help='Founder instruction authorizing this message')
    approved = sub.add_parser('select-approved', help='Stage one exact message from a verified approved source')
    approved.add_argument('--source', required=True, help='Approved source registry ID')
    approved.add_argument('--id', required=True, help='Exact Gmail message ID from list')
    approved.add_argument('--account-ref', required=True, help='Stable local account label, never an access credential')
    approved.add_argument('--confirm-review-only', action='store_true', required=True)
    approved.add_argument('--instruction-ref', required=True, help='Founder instruction authorizing this message')
    args = parser.parse_args()
    if args.action == 'list':
        if not 1 <= args.limit <= 50:
            parser.error('--limit must be 1..50')
        gmail = service()
        found = gmail.users().messages().list(userId='me', q=args.query, maxResults=args.limit).execute()
        for entry in found.get('messages', []):
            msg = gmail.users().messages().get(userId='me', id=entry['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
            h = header_map(msg.get('payload', {}))
            print(json.dumps({'id': entry['id'], 'from': h.get('from', ''), 'subject': h.get('subject', ''), 'date': h.get('date', '')}, ensure_ascii=True))
        return
    if not args.instruction_ref.strip():
        parser.error('--instruction-ref cannot be empty')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.id):
        parser.error('--id must be a single message ID, without path separators')
    if args.action == 'select-approved':
        select_approved(args)
        return
    gmail = service()
    msg = gmail.users().messages().get(userId='me', id=args.id, format='full').execute()
    if msg.get('id') != args.id:
        raise ValueError('Returned message ID does not match selected ID')
    payload = msg.get('payload', {})
    h = header_map(payload)
    content = message_body(payload)
    if not content:
        raise ValueError('No plain-text body available; no file written')
    ref = 'gmail:message:' + args.id
    source = {
        'kind': 'email', 'ref': ref, 'message_id': args.id,
        'title': h.get('subject') or '(No subject)',
        'creator': h.get('from') or '(Unknown sender)',
        'published_at': None,
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'access_basis': 'Founder selected exact Gmail message ID for review-only local staging',
        'content': content,
    }
    approval = {'source_ref': ref, 'scope': 'review_only', 'instruction_ref': args.instruction_ref}
    from discovery_review import validate_source
    validate_source(source, approval)
    STORE.mkdir(parents=True, exist_ok=True)
    path = STORE / ('gmail_selected_' + args.id + '.json')
    with path.open('x', encoding='utf-8', newline='\n') as out:
        json.dump({'source': source, 'approval': approval}, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print('STAGED:', path.name)
    print('Contains private email content. No analysis or canonical writes performed.')
    print('Next: python .\\core_intake.py prompt "' + str(path) + '"')

if __name__ == '__main__':
    main()

