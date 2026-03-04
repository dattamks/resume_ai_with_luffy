import copy

from django.test import TestCase

from analyzer.services.ai_providers.base import (
    validate_ai_response, coerce_ai_response, LLMValidationError,
)


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

    # ── Grade normalization edge cases ─────────────────────────────────────

    def test_grade_b_plus_normalized_to_b(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'B+'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')

    def test_grade_a_minus_normalized_to_a(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'A-'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'A')

    def test_grade_lowercase_normalized(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'c+'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'C')

    def test_grade_with_whitespace(self):
        data = {**VALID_RESPONSE, 'overall_grade': ' B+ '}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')

    def test_grade_with_space_before_modifier(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'B +'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')

    def test_grade_quoted(self):
        data = {**VALID_RESPONSE, 'overall_grade': '"B"'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')

    def test_grade_trailing_period(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'B.'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')

    def test_grade_double_plus(self):
        data = {**VALID_RESPONSE, 'overall_grade': 'A++'}
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'A')

    def test_grade_invalid_letter_rejected(self):
        bad = {**VALID_RESPONSE, 'overall_grade': 'E'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_grade_multi_letter_rejected(self):
        bad = {**VALID_RESPONSE, 'overall_grade': 'AB'}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)

    def test_grade_empty_rejected(self):
        bad = {**VALID_RESPONSE, 'overall_grade': ''}
        with self.assertRaises(ValueError):
            validate_ai_response(bad)


# ── Coercion layer tests ────────────────────────────────────────────────────

class CoercionTests(TestCase):
    """Tests for coerce_ai_response() — best-effort fix-up before validation."""

    def _make_response(self, **overrides):
        """Return a deep copy of VALID_RESPONSE with overrides applied."""
        data = copy.deepcopy(VALID_RESPONSE)
        for k, v in overrides.items():
            if v is None and k in data:
                del data[k]
            else:
                data[k] = v
        return data

    def _remove_key(self, key):
        data = copy.deepcopy(VALID_RESPONSE)
        del data[key]
        return data

    # ── Missing top-level fields ──

    def test_missing_job_metadata_inserted(self):
        data = self._remove_key('job_metadata')
        fixes = coerce_ai_response(data)
        self.assertIn('job_metadata', data)
        self.assertEqual(data['job_metadata']['job_title'], '')
        self.assertTrue(any('job_metadata' in f for f in fixes))
        # Should now pass validation
        validate_ai_response(data)

    def test_missing_ats_disclaimers_inserted(self):
        data = self._remove_key('ats_disclaimers')
        fixes = coerce_ai_response(data)
        self.assertIn('ats_disclaimers', data)
        self.assertIn('workday', data['ats_disclaimers'])
        self.assertTrue(any('ats_disclaimers' in f for f in fixes))
        validate_ai_response(data)

    def test_missing_summary_inserted(self):
        data = self._remove_key('summary')
        fixes = coerce_ai_response(data)
        self.assertEqual(data['summary'], '')
        validate_ai_response(data)

    def test_missing_formatting_flags_inserted(self):
        data = self._remove_key('formatting_flags')
        fixes = coerce_ai_response(data)
        self.assertEqual(data['formatting_flags'], [])
        validate_ai_response(data)

    def test_missing_overall_grade_gets_default(self):
        data = self._remove_key('overall_grade')
        fixes = coerce_ai_response(data)
        self.assertEqual(data['overall_grade'], 'C')
        validate_ai_response(data)

    # ── Scores coercion ──

    def test_scores_string_coerced_to_int(self):
        data = self._make_response(scores={
            'generic_ats': '72', 'workday_ats': '61',
            'greenhouse_ats': '68', 'keyword_match_percent': '58',
        })
        fixes = coerce_ai_response(data)
        self.assertEqual(data['scores']['generic_ats'], 72)
        self.assertTrue(any('Coerced' in f for f in fixes))
        validate_ai_response(data)

    def test_scores_out_of_range_clamped(self):
        data = self._make_response(scores={
            'generic_ats': 150, 'workday_ats': -5,
            'greenhouse_ats': 68, 'keyword_match_percent': 58,
        })
        fixes = coerce_ai_response(data)
        self.assertEqual(data['scores']['generic_ats'], 100)
        self.assertEqual(data['scores']['workday_ats'], 0)
        validate_ai_response(data)

    def test_missing_score_field_gets_default(self):
        data = self._make_response(scores={'generic_ats': 72})
        fixes = coerce_ai_response(data)
        self.assertEqual(data['scores']['workday_ats'], 50)
        validate_ai_response(data)

    def test_missing_scores_dict_entirely(self):
        data = self._remove_key('scores')
        fixes = coerce_ai_response(data)
        self.assertIn('scores', data)
        self.assertEqual(data['scores']['generic_ats'], 50)
        validate_ai_response(data)

    # ── keyword_analysis coercion ──

    def test_missing_keyword_analysis_inserted(self):
        data = self._remove_key('keyword_analysis')
        fixes = coerce_ai_response(data)
        self.assertEqual(data['keyword_analysis']['matched_keywords'], [])
        validate_ai_response(data)

    def test_missing_keyword_sub_field_inserted(self):
        data = self._make_response(keyword_analysis={'matched_keywords': ['Python']})
        fixes = coerce_ai_response(data)
        self.assertEqual(data['keyword_analysis']['missing_keywords'], [])
        validate_ai_response(data)

    # ── quick_wins coercion ──

    def test_empty_quick_wins_gets_placeholder(self):
        data = self._make_response(quick_wins=[])
        fixes = coerce_ai_response(data)
        self.assertEqual(len(data['quick_wins']), 1)
        self.assertTrue(any('placeholder' in f for f in fixes))
        validate_ai_response(data)

    def test_quick_wins_missing_priority_auto_assigned(self):
        data = self._make_response(quick_wins=[
            {'action': 'Do something'},
            {'action': 'Do another thing'},
        ])
        fixes = coerce_ai_response(data)
        self.assertEqual(data['quick_wins'][0]['priority'], 1)
        self.assertEqual(data['quick_wins'][1]['priority'], 2)
        validate_ai_response(data)

    # ── section_feedback coercion ──

    def test_section_feedback_missing_ats_flags_inserted(self):
        data = self._make_response(section_feedback=[{
            'section_name': 'Skills', 'score': 70,
            'feedback': ['Good coverage'],
            # ats_flags intentionally missing
        }])
        fixes = coerce_ai_response(data)
        self.assertEqual(data['section_feedback'][0]['ats_flags'], [])
        validate_ai_response(data)

    def test_section_feedback_score_string_coerced(self):
        data = self._make_response(section_feedback=[{
            'section_name': 'Skills', 'score': '85',
            'feedback': ['Good'], 'ats_flags': [],
        }])
        fixes = coerce_ai_response(data)
        self.assertEqual(data['section_feedback'][0]['score'], 85)
        validate_ai_response(data)

    # ── Coercion on already-valid data is no-op ──

    def test_valid_data_no_fixes(self):
        data = copy.deepcopy(VALID_RESPONSE)
        fixes = coerce_ai_response(data)
        self.assertEqual(fixes, [])

    # ── Full pipeline: coerce + validate on heavily broken response ──

    def test_full_coerce_then_validate_on_minimal_response(self):
        """Simulate an LLM that returns only overall_grade and summary."""
        data = {
            'overall_grade': 'B+',
            'summary': 'Decent resume.',
        }
        fixes = coerce_ai_response(data)
        self.assertGreater(len(fixes), 5)  # many fixes applied
        validate_ai_response(data)
        self.assertEqual(data['overall_grade'], 'B')  # B+ stripped to B


# ── LLMValidationError tests ────────────────────────────────────────────────

class LLMValidationErrorTests(TestCase):
    def test_carries_raw_response(self):
        exc = LLMValidationError('bad grade', raw_response='{"overall_grade": "B+"}')
        self.assertEqual(str(exc), 'bad grade')
        self.assertEqual(exc.raw_response, '{"overall_grade": "B+"}')

    def test_raw_response_defaults_to_none(self):
        exc = LLMValidationError('missing field')
        self.assertIsNone(exc.raw_response)
