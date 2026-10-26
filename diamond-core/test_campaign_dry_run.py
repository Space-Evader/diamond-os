"""Offline product, attribution, encoding and no-side-effect regression checks."""
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from campaign_dry_run import demo_plan, dry_run
from growth_links import PRODUCTS


class CampaignDryRunTests(unittest.TestCase):
    def setUp(self):
        self.plan = demo_plan()

    def test_all_four_registry_products_pass_and_no_network_is_used(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
            result = dry_run(self.plan)
        self.assertEqual(result['valid_count'], 4)
        self.assertEqual(result['blocked_count'], 0)
        self.assertTrue(result['ready_for_review'])
        self.assertFalse(result['published'])
        self.assertFalse(result['canonical'])
        self.assertEqual({r['rx_id'] for r in result['rows']}, {p.rx_id for p in PRODUCTS})

    def test_parameter_encoding_round_trips_without_injection(self):
        result = dry_run(self.plan)
        for row in result['rows']:
            parts = urlsplit(row['candidate_url'])
            self.assertEqual(parts.netloc, 'www.hatsrx.com')
            params = dict(parse_qsl(parts.query))
            self.assertEqual(params['utm_source'], 'friends & family')
            self.assertEqual(params['utm_medium'], 'organic+social')
            self.assertEqual(params['utm_campaign'], 'Wizard × Diamond / dry-run?')
            self.assertEqual(params['utm_content'], 'A=1&preview=only')
            self.assertNotIn('preview', params)

    def test_duplicate_attribution_blocks_both_rows_including_product_alias(self):
        row = self.plan['rows'][0]
        self.plan['rows'].append(row | {'id': 'alias', 'product': row['rx_id']})
        result = dry_run(self.plan)
        self.assertEqual(result['blocked_count'], 2)
        self.assertEqual(len(result['duplicate_attribution_groups']), 1)
        for row in (result['rows'][0], result['rows'][-1]):
            self.assertIn('duplicate_attribution', row['errors'])
            self.assertNotIn('candidate_url', row)

    def test_duplicate_row_id_blocks_both_even_with_distinct_content(self):
        row = self.plan['rows'][0]
        self.plan['rows'].append(row | {'content': 'distinct'})
        result = dry_run(self.plan)
        self.assertEqual(result['blocked_count'], 2)
        self.assertIn('duplicate_row_id', result['rows'][0]['errors'])

    def test_distinct_creative_variant_and_cross_product_campaign_are_allowed(self):
        self.plan['rows'].append(self.plan['rows'][0] | {'id': 'variant', 'content': 'creative B'})
        self.assertEqual(dry_run(self.plan)['valid_count'], 5)

    def test_case_and_unicode_equivalent_attribution_is_ambiguous(self):
        row = self.plan['rows'][0]
        row['campaign'] = 'Café'
        self.plan['rows'].append(row | {'id': 'case-variant', 'campaign': 'CAFE\u0301'})
        self.assertEqual(dry_run(self.plan)['blocked_count'], 2)

    def test_lookalike_host_credentials_port_and_non_https_rejected(self):
        destinations = [
            'https://www.hatsrx.com.evil.example/product-page/beautiful-mind-snapback-hat',
            'https://hatsrx.com@evil.example/product-page/beautiful-mind-snapback-hat',
            'https://evil.example@hatsrx.com/product-page/beautiful-mind-snapback-hat',
            'https://www.hatsrx.com:443/product-page/beautiful-mind-snapback-hat',
            'http://www.hatsrx.com/product-page/beautiful-mind-snapback-hat',
            'https://hаtsrx.com/product-page/beautiful-mind-snapback-hat',
        ]
        for destination in destinations:
            with self.subTest(destination=destination):
                plan = copy.deepcopy(self.plan)
                plan['rows'][0]['destination'] = destination
                self.assertEqual(dry_run(plan)['blocked_count'], 1)

    def test_product_key_rx_and_destination_must_match_same_entry(self):
        for fields in ({'product': 'invented'}, {'rx_id': 'HXRX-FAKE'},
                       {'destination': PRODUCTS[1].url}):
            plan = copy.deepcopy(self.plan)
            plan['rows'][0].update(fields)
            result = dry_run(plan)
            self.assertEqual(result['blocked_count'], 1)
            self.assertNotIn('candidate_url', result['rows'][0])

    def test_official_apex_and_optional_trailing_slash_are_valid(self):
        self.plan['rows'][0]['destination'] = PRODUCTS[0].url.replace('www.', '') + '/'
        self.assertEqual(dry_run(self.plan)['valid_count'], 4)

    def test_pretagged_duplicate_encoded_and_redirect_parameters_are_rejected(self):
        for query in ('utm_source=old', 'utm_source=a&UTM_SOURCE=b',
                      '%75tm_source=a&utm_source=b', 'redirect=https%3A%2F%2Fevil.example',
                      'utm_campaign=%ZZ', 'utm_campaign=%FF'):
            plan = copy.deepcopy(self.plan)
            plan['rows'][0]['destination'] = PRODUCTS[0].url + '?' + query
            self.assertEqual(dry_run(plan)['blocked_count'], 1, query)

    def test_invalid_values_unknown_fields_and_publication_requests_rejected(self):
        for fields in ({'source': ''}, {'campaign': 'private\nheader'}, {'medium': 'x' * 201},
                       {'content': None}, {'content': ''}, {'publish': True}):
            plan = copy.deepcopy(self.plan)
            plan['rows'][0].update(fields)
            self.assertEqual(dry_run(plan)['blocked_count'], 1)
        with self.assertRaises(ValueError):
            dry_run(self.plan | {'publish': True})

    def test_invalid_or_excessive_plan_rejected(self):
        for rows in ([], self.plan['rows'] * 9, 'not rows'):
            with self.assertRaises(ValueError):
                dry_run({'schema': 'diamond.hatsrx-dry-run/1', 'rows': rows})

    def test_bad_row_does_not_prevent_other_rows_being_reviewed(self):
        self.plan['rows'][0] = None
        result = dry_run(self.plan)
        self.assertEqual(result['valid_count'], 3)
        self.assertEqual(result['blocked_count'], 1)
        self.assertFalse(result['ready_for_review'])

    def test_no_files_are_written_and_registry_is_unchanged(self):
        before = tuple(PRODUCTS)
        with patch('builtins.open', side_effect=AssertionError('No file writes or reads needed')):
            self.assertEqual(dry_run(self.plan)['valid_count'], 4)
        self.assertEqual(tuple(PRODUCTS), before)


@unittest.skipIf(os.environ.get('DIAMOND_WORKER') == '1', 'CLI launched by supervising host; worker subprocess allowlist unchanged')
class CampaignDryRunCLITests(unittest.TestCase):
    def test_actual_cli_demo_from_unrelated_directory_without_writes(self):
        script = str(Path(__file__).parent / 'campaign_dry_run.py')
        with tempfile.TemporaryDirectory() as directory:
            protected = Path(directory) / 'memory.json'
            protected.write_text('unchanged')
            before = set(Path(directory).iterdir())
            result = subprocess.run([sys.executable, '-B', script, '--demo'], cwd=directory,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertEqual(json.loads(result.stdout)['valid_count'], 4)
            self.assertEqual(set(Path(directory).iterdir()), before)
            self.assertEqual(protected.read_text(), 'unchanged')

    def test_bad_plan_cli_returns_blocked_report_and_nonzero_exit(self):
        plan = demo_plan()
        plan['rows'][0]['rx_id'] = 'wrong'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            path.write_text(json.dumps(plan))
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).parent / 'campaign_dry_run.py'),
                                     '--input', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report['blocked_count'], 1)
            self.assertNotIn('candidate_url', report['rows'][0])


if __name__ == '__main__':
    unittest.main()
