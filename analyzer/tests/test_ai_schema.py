from django.test import TestCase

from analyzer.services.ai_providers.base import validate_ai_response


VALID_RESPONSE = {
    'ats_score': 72,
    'ats_score_breakdown': {
        'keyword_match': 65,
        'format_score': 80,
        'relevance_score': 71,
    },
    'keyword_gaps': ['Docker', 'Kubernetes'],
    'section_suggestions': {
        'summary': 'Add a concise summary.',
        'experience': 'Use action verbs.',
        'skills': 'List more cloud skills.',
        'education': 'Looks good.',
        'overall': 'Strong background but missing cloud keywords.',
    },
    'rewritten_bullets': [
        {
            'original': 'Worked on backend',
            'rewritten': 'Engineered RESTful APIs serving 1M+ requests/day',
            'reason': 'Added metrics and action verb.',
        }
    ],
    'overall_assessment': 'Good candidate. Add cloud skills.',
}


class AISchemaValidationTests(TestCase):
    def test_valid_response_passes(self):
        # Should not raise
        validate_ai_response(VALID_RESPONSE)

    def test_missing_ats_score(self):
        bad = {**VALID_RESPONSE}
        del bad['ats_score']
        with self.assertRaises(ValueError, msg='Missing ats_score should raise'):
            validate_ai_response(bad)

    def test_ats_score_out_of_range(self):
        bad = {**VALID_RESPONSE, 'ats_score': 150}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_ats_score_wrong_type(self):
        bad = {**VALID_RESPONSE, 'ats_score': '72'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_breakdown_field(self):
        bad = {**VALID_RESPONSE, 'ats_score_breakdown': {'keyword_match': 65}}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_section_suggestion_field(self):
        incomplete_sections = {k: v for k, v in VALID_RESPONSE['section_suggestions'].items() if k != 'overall'}
        bad = {**VALID_RESPONSE, 'section_suggestions': incomplete_sections}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_keyword_gaps_must_be_list(self):
        bad = {**VALID_RESPONSE, 'keyword_gaps': 'Docker, Kubernetes'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_overall_assessment(self):
        bad = {**VALID_RESPONSE}
        del bad['overall_assessment']
        with self.assertRaises(ValueError):
            validate_ai_response(bad)
