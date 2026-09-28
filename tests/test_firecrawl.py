import io
import json
import ssl
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch
from jobpilot.firecrawl import extract, search, request
from jobpilot.sources import tls_context


class FirecrawlTransportTests(unittest.TestCase):
    def response(self, body):
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        return opener

    def test_verified_macos_context_uses_system_bundle_when_python_has_none(self):
        with patch('jobpilot.sources.ssl.create_default_context') as create, \
             patch('jobpilot.sources.ssl.get_default_verify_paths', return_value=SimpleNamespace(cafile=None)), \
             patch('jobpilot.sources.sys.platform', 'darwin'), \
             patch('jobpilot.sources.Path.exists', return_value=True):
            context = tls_context()
        self.assertIs(context, create.return_value)
        context.load_verify_locations.assert_called_once_with(cafile='/etc/ssl/cert.pem')

    def test_existing_trust_bundle_is_preserved(self):
        with patch('jobpilot.sources.ssl.create_default_context') as create, \
             patch('jobpilot.sources.ssl.get_default_verify_paths', return_value=SimpleNamespace(cafile='/trusted/certs.pem')), \
             patch('jobpilot.sources.sys.platform', 'darwin'):
            tls_context()
        create.return_value.load_verify_locations.assert_not_called()

    def test_request_uses_verified_context_and_sends_key_only_in_header(self):
        context = ssl.create_default_context()
        opener = self.response(b'{"success":true,"data":{"web":[]}}')
        with patch('jobpilot.firecrawl.tls_context', return_value=context), \
             patch('jobpilot.firecrawl.HTTPSHandler') as https, \
             patch('jobpilot.firecrawl.build_opener', return_value=opener) as build:
            self.assertEqual(request('search', {'query': 'Python jobs'}, 'fixture-key'), {'web': []})
        https.assert_called_once_with(context=context)
        self.assertIn(https.return_value, build.call_args.args)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.firecrawl.dev/v2/search')
        self.assertEqual(req.get_header('Authorization'), 'Bearer fixture-key')
        self.assertEqual(json.loads(req.data), {'query': 'Python jobs'})
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_guest_request_has_no_authorization_header(self):
        opener = self.response(b'{"success":true,"data":{"web":[]}}')
        with patch('jobpilot.firecrawl.build_opener', return_value=opener):
            request('search', {'query': 'Python jobs'})
        self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))

    def test_http_errors_give_actionable_messages_without_echoing_upstream_body(self):
        for code, key, message in ((401, '', 'valid API key'), (402, 'key', 'credits'),
                                   (403, '', 'guest request'), (403, 'key', 'account access'),
                                   (429, '', 'rate limit'), (503, '', 'HTTP 503')):
            with self.subTest(code=code, key=key):
                body = io.BytesIO(b'private upstream details')
                opener = Mock()
                opener.open.side_effect = HTTPError('https://api.firecrawl.dev', code, 'error', {}, body)
                with patch('jobpilot.firecrawl.build_opener', return_value=opener), \
                     self.assertRaisesRegex(ValueError, message) as caught:
                    request('search', {}, key)
                self.assertNotIn('private upstream details', str(caught.exception))
                self.assertTrue(body.closed)

    def test_invalid_and_oversized_responses_are_rejected(self):
        for body in (b'<html>unavailable</html>', b'\xff', b'{}', b'{"success":true,"data":[]}',
                     b'x' * (4 * 1024 * 1024 + 1)):
            with self.subTest(size=len(body)), \
                 patch('jobpilot.firecrawl.build_opener', return_value=self.response(body)), \
                 self.assertRaisesRegex(ValueError, 'Firecrawl'):
                request('search', {})

    def test_network_failures_are_reported(self):
        for error in (URLError('offline'), TimeoutError()):
            opener = Mock()
            opener.open.side_effect = error
            with patch('jobpilot.firecrawl.build_opener', return_value=opener), \
                 self.assertRaisesRegex(ValueError, 'could not be reached'):
                request('search', {})


class FirecrawlTests(unittest.TestCase):
    def test_extract_only_sends_public_url_and_keeps_original_destination(self):
        calls = []
        def transport(endpoint, payload, key):
            calls.append((endpoint, payload, key))
            return {'json': {'title': 'Engineer', 'company': 'Example', 'description': '<p>Python role</p>', 'url': 'https://attacker.example'}}
        job = extract('https://jobs.example/123?utm_source=x', 'test-key', transport)
        self.assertEqual(job['url'], 'https://jobs.example/123')
        self.assertEqual(job['description'], 'Python role')
        self.assertEqual(calls[0][0], 'scrape')
        self.assertEqual(calls[0][1]['formats'][0]['type'], 'json')
        self.assertEqual(set(calls[0][1]), {'url', 'formats', 'timeout', 'onlyMainContent'})

    def test_rejects_nonpostings_and_unsafe_urls(self):
        with self.assertRaises(ValueError):
            extract('https://jobs.example', transport=lambda *args: {'json': {'title': 'Careers'}})
        with self.assertRaises(ValueError):
            extract('https://127.0.0.1/private', transport=lambda *args: self.fail('Should not request unsafe URL'))

    def test_search_reads_v2_web_results_and_filters_unsafe_links(self):
        def transport(endpoint, payload, key):
            self.assertEqual(endpoint, 'search')
            self.assertEqual(payload['limit'], 10)
            return {'web': [{'url': 'https://jobs.example/123', 'title': 'Engineer'}, {'url': 'javascript:alert(1)'}]}
        result = search('Python jobs India', transport=transport)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'Engineer')


if __name__ == '__main__':
    unittest.main()
