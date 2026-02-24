from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from analyzer.serializers import ResumeAnalysisCreateSerializer


def _make_pdf(content=b'%PDF-1.4 fake pdf content'):
    return SimpleUploadedFile('resume.pdf', content, content_type='application/pdf')


class ResumeFileValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='validator', password='pass123!')

    def _base_data(self):
        return {
            'jd_input_type': 'text',
            'jd_text': 'Looking for a Python developer.',
        }

    def test_valid_pdf_accepted(self):
        full_data = {**self._base_data(), 'resume_file': _make_pdf()}
        s = ResumeAnalysisCreateSerializer(data=full_data)
        self.assertTrue(s.is_valid(), s.errors)

    def test_non_pdf_extension_rejected(self):
        bad_file = SimpleUploadedFile('resume.txt', b'%PDF-fake', content_type='text/plain')
        data = {**self._base_data(), 'resume_file': bad_file}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn('resume_file', s.errors)

    def test_fake_pdf_magic_bytes_rejected(self):
        bad_file = SimpleUploadedFile('resume.pdf', b'PK\x03\x04 this is a zip', content_type='application/pdf')
        data = {**self._base_data(), 'resume_file': bad_file}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn('resume_file', s.errors)

    def test_oversized_file_rejected(self):
        big_content = b'%PDF' + b'A' * (6 * 1024 * 1024)  # 6MB
        big_file = SimpleUploadedFile('big.pdf', big_content, content_type='application/pdf')
        data = {**self._base_data(), 'resume_file': big_file}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn('resume_file', s.errors)

    def test_text_jd_requires_jd_text(self):
        data = {'jd_input_type': 'text', 'resume_file': _make_pdf()}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())

    def test_url_jd_requires_jd_url(self):
        data = {'jd_input_type': 'url', 'resume_file': _make_pdf()}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())

    def test_form_jd_requires_jd_role(self):
        data = {'jd_input_type': 'form', 'resume_file': _make_pdf()}
        s = ResumeAnalysisCreateSerializer(data=data)
        self.assertFalse(s.is_valid())
