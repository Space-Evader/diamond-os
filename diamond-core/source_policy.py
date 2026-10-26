"""Exact, explicit newsletter identities for supervised review; no network calls.

Sender identity is a routing check, not independent verification of an assertion.
Unresolved source identities stay disabled. Never trust an entire shared mail host.
"""
import hashlib
import re
from email.utils import getaddresses
from urllib.parse import urlsplit


SOURCES = {
    'superhuman': {'name': 'Superhuman', 'senders': ('superhuman@mail.joinsuperhuman.ai',),
                   'public_hosts': (), 'email_enabled': True},
    'the-code': {'name': 'The Code', 'senders': ('superhumancode@news.codenewsletter.ai',),
                 'public_hosts': (), 'email_enabled': True},
    'nautilus': {'name': 'Nautilus', 'senders': ('newsletters@nautil.us',),
                 'public_hosts': ('nautil.us', 'www.nautil.us'), 'email_enabled': True},
    'the-signal': {'name': 'The Signal (sender identity pending)', 'senders': (),
                   'public_hosts': (), 'email_enabled': False},
    'diary-of-a-ceo': {'name': 'The Diary of a CEO', 'senders': (),
                       'public_hosts': ('thediaryofaceo.com', 'www.thediaryofaceo.com'),
                       'email_enabled': False},
}


def policy(source_id):
    if source_id not in SOURCES:
        raise ValueError('Unknown approved source')
    return SOURCES[source_id]


def match_sender(sender, source_id):
    """Require one complete exact mailbox. Display names convey no authority."""
    selected = policy(source_id)
    if not selected['email_enabled']:
        raise ValueError('Email source identity has not been verified')
    if not isinstance(sender, str) or any(c in sender for c in '\r\n'):
        raise ValueError('Invalid sender header')
    parsed = getaddresses([sender])
    if len(parsed) != 1:
        raise ValueError('Exactly one sender mailbox required')
    mailbox = parsed[0][1].casefold()
    if mailbox not in selected['senders']:
        raise ValueError('Sender does not match selected approved source')
    return selected


def account_message_ref(account_ref, message_id):
    """Account-scoped identity; the account label itself is never published."""
    if not isinstance(account_ref, str) or not account_ref.strip():
        raise ValueError('A stable account reference is required')
    if not isinstance(message_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', message_id):
        raise ValueError('Invalid selected message ID')
    account_hash = hashlib.sha256(account_ref.encode('utf-8')).hexdigest()
    return f'gmail:account:{account_hash}:message:{message_id}'


def validate_public_ref(ref, source_id):
    selected = policy(source_id)
    if not isinstance(ref, str):
        raise ValueError('Public source URL required')
    try:
        parts = urlsplit(ref)
        valid = (parts.scheme == 'https' and parts.hostname in selected['public_hosts']
                 and parts.username is None and parts.password is None
                 and parts.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Public source URL is not approved for this publication')
    return selected


def validate_registered_source(source, source_id):
    if source.get('kind') == 'email':
        selected = match_sender(source.get('creator'), source_id)
        if source.get('ref') != account_message_ref(source.get('account_ref'), source.get('message_id')):
            raise ValueError('Account-scoped email source reference mismatch')
    elif source.get('kind') in ('document', 'podcast'):
        selected = validate_public_ref(source.get('ref'), source_id)
    else:
        raise ValueError('Registered intake supports email, document, or podcast')
    if source.get('source_id') != source_id:
        raise ValueError('Source registry identity mismatch')
    return selected
