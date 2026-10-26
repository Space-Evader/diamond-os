"""Focused extraction-quality checks using synthetic text only."""
import unittest

from learning_pipeline import extract_envelope


class LearningQualityTests(unittest.TestCase):
    def extract(self, content):
        source = {
            'kind': 'document', 'source_id': 'nautilus',
            'ref': 'https://nautil.us/synthetic-quality-check/',
            'title': 'Synthetic quality check', 'creator': 'Synthetic author',
            'captured_at': '2026-10-25T12:00:00+00:00',
            'access_basis': 'Synthetic offline fixture; no source retrieval',
            'content': content,
        }
        approval = {'source_ref': source['ref'], 'scope': 'review_only',
                    'instruction_ref': 'Synthetic quality review'}
        return extract_envelope(source, approval, 'Synthetic reviewer',
                                '2026-10-25T12:01:00+00:00', ['Diamond Core'])

    def test_greetings_issue_summaries_and_section_headers_are_skipped(self):
        assertion = 'Researchers found a measurable difference between the two experimental conditions.'
        content = (
            'Hello readers, welcome to another newsletter full of the latest science discoveries.\n'
            'In this issue we have assembled three stories for your reading pleasure.\n'
            'THE THREE THINGS YOU NEED TO READ BEFORE YOU START YOUR DAY\n'
            'Topics and useful links included for your next reading session:\n'
            + assertion
        )
        packet = self.extract(content)
        self.assertEqual([i['excerpt'] for i in packet['analysis']['ideas']], [assertion])
        span = packet['source']['evidence_spans'][0]
        self.assertEqual(content[span['start']:span['end']], assertion)

    def test_inline_provenance_link_retains_exact_original_assertion(self):
        assertion = 'Researchers found a measurable difference between the two experimental conditions.'
        content = '  ' + assertion + ' https://nautil.us/synthetic-study/'
        packet = self.extract(content)
        self.assertEqual(packet['analysis']['ideas'][0]['excerpt'], assertion)
        span = packet['source']['evidence_spans'][0]
        self.assertEqual((span['start'], span['end']), (2, 2 + len(assertion)))
        self.assertEqual(content[span['start']:span['end']], assertion)
        self.assertEqual(packet['analysis']['ideas'][0]['evidence_state'], 'UNRESOLVED')

    def test_declarative_prose_ranks_ahead_of_link_adjacent_headings(self):
        headings = '\n'.join(
            f'A collection of curious science headlines and reading ideas number {i} https://nautil.us/item-{i}/'
            for i in range(3)
        )
        assertion = 'Researchers found a measurable difference between the two experimental conditions.'
        packet = self.extract(headings + '\n' + assertion)
        self.assertEqual(packet['analysis']['ideas'][0]['excerpt'], assertion)

    def test_all_boilerplate_requires_manual_review_instead_of_fake_ideas(self):
        content = (
            'Welcome to the weekly newsletter with everything you might want to read.\n'
            'In today’s edition we have collected our highlights for the week.\n'
            'Presented by our partner who makes this free publication possible.'
        )
        with self.assertRaisesRegex(ValueError, 'No suitable text spans'):
            self.extract(content)


if __name__ == '__main__':
    unittest.main()
