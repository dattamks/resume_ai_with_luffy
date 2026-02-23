from django.test import TestCase

from analyzer.services.ai_providers.base import validate_ai_response


VALID_RESPONSE = {
    'job_metadata': {
        'job_title': 'Backend Engineer',
        'company': 'Acme Corp',
        'skills': 'Python, Django, Docker',
        'experience_years': 3,
        'industry': 'SaaS',
        'extra_details': 'Remote-friendly role. Team of 8 engineers. Series B startup.',
    },
    'overall_grade': 'B',
    'scores': {
        'generic_ats': 72,
        'workday_ats': 61,
        'greenhouse_ats': 68,
        'keyword_match_percent': 58,
    },
    'ats_disclaimers': {
        'workday': 'Simulated score based on known Workday parsing behavior.',
        'greenhouse': 'Simulated score based on known Greenhouse parsing behavior.',
    },
    'keyword_analysis': {
        'matched_keywords': ['Python', 'Django'],
        'missing_keywords': ['Docker', 'Kubernetes'],
        'recommended_to_add': ['Add Docker to skills section'],
    },
    'section_feedback': [
        {
            'section_name': 'Work Experience',
            'score': 65,
            'feedback': ['Add quantified impact', 'Use stronger action verbs'],
            'ats_flags': [],
        },
    ],
    'sentence_suggestions': [
        {
            'original': 'Worked on backend',
            'suggested': 'Engineered RESTful APIs serving 1M+ requests/day',
            'reason': 'Added metrics and action verb.',
        },
    ],
    'formatting_flags': ['Multi-column layout detected'],
    'quick_wins': [
        {'priority': 1, 'action': 'Add missing keywords Docker and Kubernetes'},
        {'priority': 2, 'action': 'Remove multi-column layout'},
        {'priority': 3, 'action': 'Quantify bullet points'},
    ],
    'summary': 'Good candidate. Add cloud skills and quantify achievements.',
}


class AISchemaValidationTests(TestCase):
    def test_valid_response_passes(self):
        # Should not raise
        validate_ai_response(VALID_RESPONSE)

    def test_missing_scores(self):
        bad = {**VALID_RESPONSE}
        del bad['scores']
        with self.assertRaises(ValueError, msg='Missing scores should raise'):
            validate_ai_response(bad)

    def test_score_out_of_range(self):
        bad = {**VALID_RESPONSE, 'scores': {
            'generic_ats': 150, 'workday_ats': 61,
            'greenhouse_ats': 68, 'keyword_match_percent': 58,
        }}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_scores_wrong_type(self):
        bad = {**VALID_RESPONSE, 'scores': 'not a dict'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_scores_sub_field(self):
        bad = {**VALID_RESPONSE, 'scores': {'generic_ats': 72}}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_invalid_overall_grade(self):
        bad = {**VALID_RESPONSE, 'overall_grade': 'X'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_keyword_analysis_sub_field(self):
        bad = {**VALID_RESPONSE, 'keyword_analysis': {'matched_keywords': []}}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_section_feedback_must_be_list(self):
        bad = {**VALID_RESPONSE, 'section_feedback': 'not a list'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_section_feedback_entry_missing_key(self):
        bad = {**VALID_RESPONSE, 'section_feedback': [{'section_name': 'Skills'}]}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_quick_wins_entry_missing_key(self):
        bad = {**VALID_RESPONSE, 'quick_wins': [{'priority': 1}]}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_summary(self):
        bad = {**VALID_RESPONSE}
        del bad['summary']
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_job_metadata(self):
        bad = {**VALID_RESPONSE}
        del bad['job_metadata']
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_missing_job_metadata_sub_field(self):
        bad = {**VALID_RESPONSE, 'job_metadata': {'job_title': 'Dev'}}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)
