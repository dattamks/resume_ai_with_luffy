"""
Skill catalogue URL routes.

Mounted under ``/api/v1/skills/`` in the root URL configuration.
"""
from django.urls import path

from .views_skills import SkillListView, SkillDetailView

skills_urlpatterns = [
    path('', SkillListView.as_view(), name='skill-list'),
    path('<str:name>/', SkillDetailView.as_view(), name='skill-detail'),
]
