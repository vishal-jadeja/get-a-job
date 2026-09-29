"""Read-only Gmail OAuth and bounded message retrieval. No send/modify scopes."""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler
from .sources import NoRedirect, tls_context, plain

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN = 'https://oauth2.googleapis.com/token'
API = 'https://gmail.googleapis.com/gmail/v1/users/me/'
DEFAULT_QUERY = 'newer_than:90d {"application received" "thank you for applying" "your application" "interview" "offer of employment"}'


def request(url, data=None, token=None):
    if url != TOKEN and not url.startswith(API):
        raise ValueError('Unsupported Google endpoint')
    headers = {'Accept': 'application/json', 'User-Agent': 'JobPilot/3.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = urlencode(data).encode() if data is not None else None
    if body is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    try:
        with build_opener(NoRedirect, HTTPSHandler(context=tls_context())).open(Request(url, data=body, headers=headers), timeout=30) as response:
            raw = response.read(3 * 1024 * 1024 + 1)
        if len(raw) > 3 * 1024 * 1024:
            raise ValueError('Google response was too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Google returned an unexpected response')
        return result
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise ValueError(f'Google request failed (HTTP {code}). Reconnect Gmail or check that Gmail API is enabled. No mailbox changes were made.') from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('Google could not be reached or returned an invalid response. Try again later.') from None


def body_text(payload, depth=0):
    if depth > 15 or not isinstance(payload, dict):
        return ''
    if payload.get('filename'):
        return ''  # Attachments are never downloaded.
    mime = payload.get('mimeType', '')
    if mime in ('text/plain', 'text/html'):
        encoded = payload.get('body', {}).get('data', '')
        if not isinstance(encoded, str) or len(encoded) > 150000:
            return ''
        try:
            value = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8', errors='replace')
        except (ValueError, TypeError):
            return ''
        return (plain(value) if mime == 'text/html' else value)[:60000]
    parts = payload.get('parts', [])[:100]
    if mime == 'multipart/alternative':
        text = next((p for p in parts if p.get('mimeType') == 'text/plain'), None)
        if text is not None:
            return body_text(text, depth+1)
    return '\n'.join(body_text(p, depth+1) for p in parts)[:60000]


def normalize_message(raw):
    mid = str(raw.get('id', ''))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', mid):
        raise ValueError('Invalid Gmail message identifier')
    payload = raw.get('payload', {})
    headers = {str(h.get('name', '')).lower(): str(h.get('value', '')) for h in payload.get('headers', [])}
    return {'id': mid, 'subject': headers.get('subject', '')[:1000], 'sender': headers.get('from', '')[:1000],
            'received_at': str(raw.get('internalDate', '')), 'text': body_text(payload),
            'url': 'https://mail.google.com/mail/u/0/#all/' + mid}


class Gmail:
    def __init__(self, directory, transport=request):
        self.path = Path(directory) / 'gmail-credentials.json'
        self.transport = transport
        self.lock = threading.RLock()
        self.pending = None
        self.credentials = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.access = None
        self.expires = 0

    def _save(self):
        temp = self.path.with_suffix('.tmp')
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(self.credentials, stream)
        temp.replace(self.path)
        self.path.chmod(0o600)

    def status(self):
        with self.lock:
            return {'configured': bool(self.credentials.get('client_id')), 'connected': bool(self.credentials.get('refresh_token')),
                    'email': self.credentials.get('email', ''), 'scope': SCOPE}

    def configure(self, data):
        installed = data.get('installed') if isinstance(data, dict) else None
        if not isinstance(installed, dict):
            raise ValueError('Upload the Google OAuth client JSON for a Desktop app (installed client)')
        client_id, secret = installed.get('client_id'), installed.get('client_secret')
        if not isinstance(client_id, str) or not client_id.endswith('.apps.googleusercontent.com') or len(client_id) > 300:
            raise ValueError('Invalid Google Desktop client ID')
        if not isinstance(secret, str) or not 1 <= len(secret) <= 500 or any(ord(c) < 32 for c in secret):
            raise ValueError('Invalid Google Desktop client configuration')
        with self.lock:
            if self.credentials.get('refresh_token'):
                raise ValueError('Disconnect the current Gmail account before replacing its client configuration')
            self.credentials = {'client_id': client_id, 'client_secret': secret}
            self._save()
        return self.status()

    def connect_url(self, port):
        with self.lock:
            if not self.credentials.get('client_id'):
                raise ValueError('Configure your Google Desktop OAuth client first')
            verifier = secrets.token_urlsafe(48)
            state = secrets.token_urlsafe(32)
            redirect = f'http://127.0.0.1:{port}/oauth/gmail/callback'
            self.pending = {'state': state, 'verifier': verifier, 'redirect_uri': redirect, 'expires': time.time()+600}
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            return AUTH + '?' + urlencode({'client_id': self.credentials['client_id'], 'redirect_uri': redirect,
                'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent',
                'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def callback(self, state, code, error=''):
        with self.lock:
            pending = self.pending
            if not pending or time.time() > pending['expires'] or not secrets.compare_digest(str(state), pending['state']):
                raise ValueError('Gmail connection request expired or has an invalid state. Start again from JobPilot.')
            self.pending = None
            if error or not code:
                raise ValueError('Gmail connection was not approved. No mailbox was read.')
            result = self.transport(TOKEN, {'client_id': self.credentials['client_id'], 'client_secret': self.credentials['client_secret'],
                'code': code, 'grant_type': 'authorization_code', 'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['verifier']})
            refresh = result.get('refresh_token')
            if not refresh or not result.get('access_token'):
                raise ValueError('Google did not return offline access. Disconnect/reconnect and grant the requested read-only permission.')
            # Check the granted scope when supplied; never silently claim read-only access otherwise.
            if result.get('scope') and SCOPE not in result['scope'].split():
                raise ValueError('The requested Gmail read-only permission was not granted')
            profile = self.transport(API+'profile', token=result['access_token'])
            self.credentials.update(refresh_token=refresh, email=profile.get('emailAddress', ''))
            self.access, self.expires = result['access_token'], time.time()+int(result.get('expires_in', 3600))-60
            self._save()
        return self.status()

    def token(self):
        with self.lock:
            if not self.credentials.get('refresh_token'):
                raise ValueError('Connect Gmail first')
            if not self.access or time.time() >= self.expires:
                result = self.transport(TOKEN, {'client_id': self.credentials['client_id'], 'client_secret': self.credentials['client_secret'],
                    'refresh_token': self.credentials['refresh_token'], 'grant_type': 'refresh_token'})
                if not result.get('access_token'):
                    raise ValueError('Gmail authorization expired. Reconnect the account.')
                self.access, self.expires = result['access_token'], time.time()+int(result.get('expires_in', 3600))-60
            return self.access

    def messages(self, query=DEFAULT_QUERY, limit=50):
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 1000 or not 1 <= limit <= 100:
            raise ValueError('Use a search query and a limit of 1–100 messages')
        access = self.token()
        params = {'q': query, 'maxResults': min(limit, 100), 'includeSpamTrash': 'false'}
        count = 0
        account = self.status()['email']
        while count < limit:
            if not self.status()['connected'] or self.status()['email'] != account:
                raise ValueError('Gmail was disconnected or changed; sync stopped')
            page = self.transport(API+'messages?'+urlencode(params), token=access)
            for item in page.get('messages', []):
                if not self.status()['connected'] or self.status()['email'] != account:
                    raise ValueError('Gmail was disconnected or changed; sync stopped')
                mid = str(item.get('id', ''))
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', mid):
                    continue
                raw = self.transport(API+'messages/'+mid+'?format=full', token=access)
                yield normalize_message(raw)
                count += 1
                if count >= limit:
                    return
            if not page.get('nextPageToken'):
                return
            params['pageToken'] = page['nextPageToken']
            params['maxResults'] = limit-count

    def disconnect(self):
        # This removes local access; the user can also revoke it in Google Account settings.
        with self.lock:
            self.credentials = {k: v for k, v in self.credentials.items() if k in ('client_id', 'client_secret')}
            self.access, self.pending, self.expires = None, None, 0
            self._save()
        return self.status()
