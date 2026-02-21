from django.contrib import admin
from .models import ResumeAnalysis


@admin.register(ResumeAnalysis)
class ResumeAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'jd_role', 'jd_company', 'status', 'ats_score', 'created_at')
    list_filter = ('status', 'jd_input_type', 'ai_provider_used')
    search_fields = ('user__username', 'jd_role', 'jd_company')
    readonly_fields = ('resume_text', 'resolved_jd', 'created_at', 'updated_at')
