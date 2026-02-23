"""
Tests for Job endpoints:
  GET    /api/jobs/                     — List tracked jobs
  POST   /api/jobs/                     — Create a tracked job
  GET    /api/jobs/<uuid>/              — Retrieve a job
  DELETE /api/jobs/<uuid>/              — Delete a job
  POST   /api/jobs/<uuid>/relevant/     — Mark job as relevant
  POST   /api/jobs/<uuid>/irrelevant/   — Mark job as irrelevant
"""
import uuid

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import Job, Resume


def _make_pdf(content=b'%PDF-1.4 fake content'):
    return SimpleUploadedFile('resume.pdf', content, content_type='application/pdf')


def _auth(client, username='jobuser', password='StrongPass123!'):
    user = User.objects.create_user(username=username, password=password)
    resp = client.post('/api/auth/login/', {'username': username, 'password': password}, format='json')
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client, user


class JobListCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client, self.user = _auth(self.client)
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

    def test_list_empty(self):
        resp = self.client.get('/api/jobs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_create_job_minimal(self):
        resp = self.client.post('/api/jobs/', {
            'job_url': 'https://example.com/job/123',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('id', resp.data)
        self.assertEqual(resp.data['job_url'], 'https://example.com/job/123')
        self.assertEqual(resp.data['relevance'], 'pending')

    def test_create_job_full(self):
        resp = self.client.post('/api/jobs/', {
            'job_url': 'https://example.com/job/456',
            'title': 'Senior Dev',
            'company': 'Acme Corp',
            'description': 'Build cool stuff',
            'source': 'linkedin',
            'resume_id': str(self.resume.id),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['title'], 'Senior Dev')
        self.assertEqual(resp.data['company'], 'Acme Corp')
        self.assertEqual(str(resp.data['resume']), str(self.resume.id))
        self.assertEqual(resp.data['resume_filename'], 'resume.pdf')

    def test_create_job_invalid_resume_id(self):
        resp = self.client.post('/api/jobs/', {
            'job_url': 'https://example.com/job/789',
            'resume_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_job_other_users_resume(self):
        other = User.objects.create_user(username='otherj', password='StrongPass123!')
        other_resume, _ = Resume.get_or_create_from_upload(other, _make_pdf(b'%PDF-1.4 other'))
        resp = self.client.post('/api/jobs/', {
            'job_url': 'https://example.com/job/999',
            'resume_id': str(other_resume.id),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_with_data(self):
        Job.objects.create(user=self.user, job_url='https://a.com/1', title='Job A')
        Job.objects.create(user=self.user, job_url='https://b.com/2', title='Job B')
        resp = self.client.get('/api/jobs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_list_user_isolation(self):
        """Users only see their own jobs."""
        other = User.objects.create_user(username='otherj2', password='StrongPass123!')
        Job.objects.create(user=other, job_url='https://other.com/1', title='Other Job')
        Job.objects.create(user=self.user, job_url='https://mine.com/1', title='My Job')
        resp = self.client.get('/api/jobs/')
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['title'], 'My Job')

    def test_list_filter_by_relevance(self):
        Job.objects.create(user=self.user, job_url='https://a.com/1', relevance='relevant')
        Job.objects.create(user=self.user, job_url='https://b.com/2', relevance='irrelevant')
        Job.objects.create(user=self.user, job_url='https://c.com/3', relevance='pending')

        resp = self.client.get('/api/jobs/?relevance=relevant')
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['relevance'], 'relevant')

    def test_requires_auth(self):
        resp = APIClient().get('/api/jobs/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class JobDetailDeleteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='jduser')
        self.job = Job.objects.create(
            user=self.user, job_url='https://example.com/job/1', title='Test Job',
        )

    def test_get_detail(self):
        resp = self.client.get(f'/api/jobs/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'Test Job')

    def test_get_other_user_404(self):
        other = User.objects.create_user(username='other3', password='StrongPass123!')
        other_job = Job.objects.create(user=other, job_url='https://x.com/1')
        resp = self.client.get(f'/api/jobs/{other_job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_job(self):
        resp = self.client.delete(f'/api/jobs/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Job.objects.filter(id=self.job.id).exists())

    def test_delete_other_user_404(self):
        other = User.objects.create_user(username='other4', password='StrongPass123!')
        other_job = Job.objects.create(user=other, job_url='https://y.com/1')
        resp = self.client.delete(f'/api/jobs/{other_job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_nonexistent_404(self):
        resp = self.client.delete(f'/api/jobs/{uuid.uuid4()}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class JobRelevanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='reluser')
        self.job = Job.objects.create(
            user=self.user, job_url='https://example.com/job/2', title='Relevance Job',
        )

    def test_mark_relevant(self):
        resp = self.client.post(f'/api/jobs/{self.job.id}/relevant/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['relevance'], 'relevant')
        self.job.refresh_from_db()
        self.assertEqual(self.job.relevance, 'relevant')

    def test_mark_irrelevant(self):
        resp = self.client.post(f'/api/jobs/{self.job.id}/irrelevant/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['relevance'], 'irrelevant')

    def test_toggle_relevance(self):
        """Can change from relevant to irrelevant."""
        self.client.post(f'/api/jobs/{self.job.id}/relevant/')
        resp = self.client.post(f'/api/jobs/{self.job.id}/irrelevant/')
        self.assertEqual(resp.data['relevance'], 'irrelevant')

    def test_other_user_404(self):
        other = User.objects.create_user(username='other5', password='StrongPass123!')
        other_job = Job.objects.create(user=other, job_url='https://z.com/1')
        resp = self.client.post(f'/api/jobs/{other_job.id}/relevant/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
