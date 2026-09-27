import unittest
from jobpilot.firecrawl import extract, search


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
