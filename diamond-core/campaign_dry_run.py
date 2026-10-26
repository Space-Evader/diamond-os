"""Offline HatsRx campaign preflight using the recovered product registry.

No network calls, publishing, files written, analytics installation or commerce
changes. Registry identity is checked, not live stock, sales or storefront health.
"""
import argparse
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

from discovery_review import digest
from growth_links import PRODUCTS, generate_link, get_product, validate_product_url
from learning_cycle import read_json


def _inspect(row):
    if not isinstance(row, dict):
        raise ValueError('invalid_row')
    required = {'id', 'product', 'rx_id', 'source', 'medium', 'campaign'}
    if not required <= set(row) <= required | {'content', 'destination'}:
        raise ValueError('invalid_row_fields')
    if not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', row['id']):
        raise ValueError('invalid_row_id')
    entry = get_product(row['product'])
    if row['rx_id'] != entry.rx_id:
        raise ValueError('rx_identifier_mismatch')
    destination = row.get('destination', entry.url)
    try:
        validate_product_url(destination)
        parts = urlsplit(destination)
        if parts.path.rstrip('/') != urlsplit(entry.url).path.rstrip('/'):
            raise ValueError('product_destination_mismatch')
        if re.search(r'%(?![0-9A-Fa-f]{2})', parts.query):
            raise ValueError('invalid_parameter_encoding')
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, errors='strict', max_num_fields=32)
        keys = [key.casefold() for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate_destination_parameters')
        if any(key.startswith('utm_') for key in keys):
            raise ValueError('pretagged_destination')
        if pairs:
            raise ValueError('unapproved_destination_parameters')
    except (TypeError, UnicodeError) as exc:
        raise ValueError('invalid_destination_encoding') from exc
    generated = generate_link(entry.key, row['source'], row['medium'], row['campaign'], row.get('content'))
    expected = [(f'utm_{key}', row[key].strip()) for key in ('source', 'medium', 'campaign')]
    if 'content' in row:
        # Explicit null is ambiguous; omitting the field is the only no-content form.
        if row['content'] is None:
            raise ValueError('invalid_content')
        expected.append(('utm_content', row['content'].strip()))
    actual = parse_qsl(urlsplit(generated['url']).query, keep_blank_values=True, errors='strict')
    if actual != expected or len(actual) != len(dict(actual)):
        raise ValueError('parameter_round_trip_failed')
    identity = digest({'rx_id': entry.rx_id, 'attribution': [
        (key, unicodedata.normalize('NFC', value).casefold()) for key, value in expected]})
    return {'id': row['id'], 'product': entry.key, 'rx_id': entry.rx_id,
            'candidate_url': generated['url'], 'attribution_identity': identity, 'errors': []}


def dry_run(plan):
    """Validate all rows; duplicates invalidate both entries, never first-wins."""
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'rows'}
            or plan['schema'] != 'diamond.hatsrx-dry-run/1'
            or not isinstance(plan['rows'], list) or not 1 <= len(plan['rows']) <= 32):
        raise ValueError('Exact bounded diamond.hatsrx-dry-run/1 plan required')
    reports, by_id, by_attribution = [], {}, {}
    for index, row in enumerate(plan['rows']):
        try:
            report = _inspect(row)
        except (ValueError, TypeError, UnicodeError) as exc:
            label = row.get('id') if isinstance(row, dict) else None
            if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', label):
                label = None
            report = {'id': label, 'errors': [str(exc) or 'invalid_row']}
        report['row_number'] = index + 1
        reports.append(report)
        if report['id'] is not None:
            by_id.setdefault(report['id'], []).append(index)
        if 'attribution_identity' in report:
            by_attribution.setdefault(report['attribution_identity'], []).append(index)
    duplicates = []
    for groups, error in ((by_id, 'duplicate_row_id'), (by_attribution, 'duplicate_attribution')):
        for identity, indexes in groups.items():
            if len(indexes) > 1:
                for index in indexes:
                    reports[index]['errors'].append(error)
                if error == 'duplicate_attribution':
                    duplicates.append({'identity': identity, 'row_numbers': [i + 1 for i in indexes]})
    for report in reports:
        report['valid'] = not report['errors']
        if not report['valid']:
            report.pop('candidate_url', None)
    valid = sum(row['valid'] for row in reports)
    return {'schema': 'diamond.hatsrx-dry-run-result/1', 'mode': 'offline_dry_run',
            'rows': reports, 'valid_count': valid, 'blocked_count': len(reports) - valid,
            'duplicate_attribution_groups': duplicates, 'ready_for_review': valid == len(reports),
            'inventory_basis': 'Recovered product registry observed 2026-10-25; not live stock or analytics verification',
            'published': False, 'canonical': False, 'review_required': True}


def demo_plan():
    return {'schema': 'diamond.hatsrx-dry-run/1', 'rows': [
        {'id': product.key, 'product': product.key, 'rx_id': product.rx_id,
         'source': 'friends & family', 'medium': 'organic+social',
         'campaign': 'Wizard × Diamond / dry-run?', 'content': 'A=1&preview=only'}
        for product in PRODUCTS]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', help='Private JSON campaign plan')
    group.add_argument('--demo', action='store_true', help='Four registry products with illustrative attribution')
    args = parser.parse_args()
    try:
        result = dry_run(demo_plan() if args.demo else read_json(args.input))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['ready_for_review']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
