"""
Admin Daily Digest — aggregation service.

Computes ~40 metrics across 11 categories for the past 24 hours.
Called by the `send_admin_digest_task` Celery task twice daily (9 AM + 11 PM IST).
"""

import logging
from datetime import timedelta
from collections import Counter

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

logger = logging.getLogger('analyzer')

# IST offset for display purposes
IST_OFFSET = timedelta(hours=5, minutes=30)


def _safe_round(value, decimals=1):
    """Round a value safely, returning '—' for None."""
    if value is None:
        return '—'
    return round(value, decimals)


def compute_digest_metrics() -> dict:
    """
    Compute all admin digest metrics for the last 24 hours.

    Returns a dict with 11 sections:
        users, revenue, credits, analyses, resumes,
        llm, job_alerts, features, news, notifications, infra
    """
    from analyzer.models import (
        CoverLetter,
        DiscoveredJob,
        InterviewPrep,
        JobAlert,
        JobAlertRun,
        JobMatch,
        LLMResponse,
        NewsSnippet,
        Notification,
        Resume,
        ResumeAnalysis,
        ResumeChat,
        SentAlert,
        UserActivity,
        GeneratedResume,
    )
    from accounts.models import (
        ContactSubmission,
        RazorpayPayment,
        RazorpaySubscription,
        UserProfile,
        Wallet,
        WalletTransaction,
        WebhookEvent,
    )

    now = timezone.now()
    since = now - timedelta(hours=24)
    today_date = (now + IST_OFFSET).date()  # IST date

    # ── 1. Users & Signups ───────────────────────────────────────────────
    new_users = User.objects.filter(date_joined__gte=since)
    new_signups = new_users.count()

    # Plan distribution (all users)
    plan_dist = dict(
        UserProfile.objects
        .values_list('plan__name')
        .annotate(c=Count('id'))
        .order_by('-c')
    )

    # Auth provider distribution (new users only)
    auth_providers = dict(
        UserProfile.objects
        .filter(user__date_joined__gte=since)
        .values_list('auth_provider')
        .annotate(c=Count('id'))
        .order_by('-c')
    )

    # DAU
    dau = UserActivity.objects.filter(date=today_date).values('user').distinct().count()

    # Total users
    total_users = User.objects.count()

    users = {
        'new_signups': new_signups,
        'total_users': total_users,
        'dau': dau,
        'plan_distribution': plan_dist,
        'auth_providers': auth_providers,
    }

    # ── 2. Revenue & Payments ────────────────────────────────────────────
    payments_24h = RazorpayPayment.objects.filter(created_at__gte=since)

    captured = payments_24h.filter(status='captured')
    captured_count = captured.count()
    # amount is in paise, convert to INR
    captured_total_inr = (captured.aggregate(s=Sum('amount'))['s'] or 0) / 100

    failed_payments = payments_24h.filter(status='failed').count()

    new_subs = RazorpaySubscription.objects.filter(created_at__gte=since).count()

    sub_status_dist = dict(
        RazorpaySubscription.objects
        .values_list('status')
        .annotate(c=Count('id'))
        .order_by('-c')
    )

    webhooks_24h = WebhookEvent.objects.filter(created_at__gte=since).count()

    revenue = {
        'captured_count': captured_count,
        'captured_total_inr': float(captured_total_inr),
        'failed_payments': failed_payments,
        'new_subscriptions': new_subs,
        'subscription_status': sub_status_dist,
        'webhooks_received': webhooks_24h,
    }

    # ── 3. Credit Economy ────────────────────────────────────────────────
    txns_24h = WalletTransaction.objects.filter(created_at__gte=since)

    credits_by_type = dict(
        txns_24h
        .values_list('transaction_type')
        .annotate(total=Sum('amount'))
        .order_by()
    )

    zero_balance_users = Wallet.objects.filter(balance=0).count()

    credits = {
        'plan_credits_granted': float(credits_by_type.get('plan_credit', 0)),
        'topup_credits': float(credits_by_type.get('topup', 0)),
        'credits_consumed': abs(float(credits_by_type.get('analysis_debit', 0))),
        'credits_refunded': float(credits_by_type.get('refund', 0)),
        'admin_adjustments': float(credits_by_type.get('admin_adjustment', 0)),
        'zero_balance_users': zero_balance_users,
    }

    # ── 4. Resume Analyses ───────────────────────────────────────────────
    analyses_24h = ResumeAnalysis.objects.filter(created_at__gte=since)
    analyses_total = analyses_24h.count()

    analyses_by_status = dict(
        analyses_24h
        .values_list('status')
        .annotate(c=Count('id'))
        .order_by()
    )

    done_analyses = analyses_24h.filter(status=ResumeAnalysis.STATUS_DONE)
    avg_ats = done_analyses.aggregate(avg=Avg('ats_score'))['avg']
    avg_grade = done_analyses.aggregate(avg=Avg('overall_grade'))['avg']

    analyses = {
        'total': analyses_total,
        'done': analyses_by_status.get('done', 0),
        'failed': analyses_by_status.get('failed', 0),
        'processing': analyses_by_status.get('processing', 0),
        'pending': analyses_by_status.get('pending', 0),
        'avg_ats_score': _safe_round(avg_ats),
        'avg_overall_grade': _safe_round(avg_grade),
    }

    # ── 5. Resume Uploads & Generation ───────────────────────────────────
    resumes_24h = Resume.objects.filter(uploaded_at__gte=since)
    resumes_uploaded = resumes_24h.count()

    resume_status_dist = dict(
        resumes_24h
        .values_list('processing_status')
        .annotate(c=Count('id'))
        .order_by()
    )

    generated_24h = GeneratedResume.objects.filter(created_at__gte=since)
    generated_count = generated_24h.count()
    generated_by_format = dict(
        generated_24h
        .values_list('format')
        .annotate(c=Count('id'))
        .order_by()
    )

    builder_sessions = ResumeChat.objects.filter(created_at__gte=since)
    builder_by_status = dict(
        builder_sessions
        .values_list('status')
        .annotate(c=Count('id'))
        .order_by()
    )

    resumes = {
        'uploaded': resumes_uploaded,
        'processing_status': resume_status_dist,
        'generated': generated_count,
        'generated_by_format': generated_by_format,
        'builder_sessions': builder_sessions.count(),
        'builder_by_status': builder_by_status,
    }

    # ── 6. LLM Usage & Cost ──────────────────────────────────────────────
    llm_24h = LLMResponse.objects.filter(created_at__gte=since)
    llm_total_calls = llm_24h.count()

    llm_by_purpose = dict(
        llm_24h
        .values_list('call_purpose')
        .annotate(c=Count('id'))
        .order_by('-c')
    )

    llm_aggs = llm_24h.aggregate(
        total_prompt_tokens=Sum('prompt_tokens'),
        total_completion_tokens=Sum('completion_tokens'),
        total_tokens=Sum('total_tokens'),
        total_cost=Sum('estimated_cost_usd'),
        avg_duration=Avg('duration_seconds'),
    )

    llm_failed = llm_24h.filter(status='failed').count()
    llm_failure_rate = (
        round(llm_failed / llm_total_calls * 100, 1) if llm_total_calls > 0 else 0
    )

    llm = {
        'total_calls': llm_total_calls,
        'by_purpose': llm_by_purpose,
        'prompt_tokens': llm_aggs['total_prompt_tokens'] or 0,
        'completion_tokens': llm_aggs['total_completion_tokens'] or 0,
        'total_tokens': llm_aggs['total_tokens'] or 0,
        'estimated_cost_usd': _safe_round(llm_aggs['total_cost'], 4),
        'avg_duration_sec': _safe_round(llm_aggs['avg_duration'], 2),
        'failed': llm_failed,
        'failure_rate_pct': llm_failure_rate,
    }

    # ── 7. Job Alerts & Matching ─────────────────────────────────────────
    runs_24h = JobAlertRun.objects.filter(created_at__gte=since)
    runs_count = runs_24h.count()

    runs_aggs = runs_24h.aggregate(
        jobs_discovered=Sum('jobs_discovered'),
        jobs_matched=Sum('jobs_matched'),
    )

    new_jobs = DiscoveredJob.objects.filter(created_at__gte=since).count()
    new_matches = JobMatch.objects.filter(created_at__gte=since)
    new_matches_count = new_matches.count()
    avg_relevance = new_matches.aggregate(avg=Avg('relevance_score'))['avg']

    sent_alerts = SentAlert.objects.filter(sent_at__gte=since)
    alerts_by_channel = dict(
        sent_alerts
        .values_list('channel')
        .annotate(c=Count('id'))
        .order_by()
    )

    active_alerts_total = JobAlert.objects.filter(is_active=True).count()

    job_alerts = {
        'alert_runs': runs_count,
        'jobs_discovered': runs_aggs['jobs_discovered'] or 0,
        'jobs_matched': runs_aggs['jobs_matched'] or 0,
        'new_discovered_jobs': new_jobs,
        'new_matches': new_matches_count,
        'avg_relevance_score': _safe_round(avg_relevance),
        'alerts_sent_email': alerts_by_channel.get('email', 0),
        'alerts_sent_in_app': alerts_by_channel.get('in_app', 0),
        'active_alerts_total': active_alerts_total,
    }

    # ── 8. Feature Usage ─────────────────────────────────────────────────
    interview_preps = InterviewPrep.objects.filter(created_at__gte=since).count()
    cover_letters = CoverLetter.objects.filter(created_at__gte=since).count()

    # Activity breakdown
    activity_today = UserActivity.objects.filter(date=today_date)
    activity_agg = activity_today.aggregate(total_actions=Sum('action_count'))
    total_actions = activity_agg['total_actions'] or 0

    # Aggregate action type counts from JSON field
    action_breakdown = Counter()
    for ua in activity_today.only('actions'):
        if ua.actions:
            for action_type, count in ua.actions.items():
                action_breakdown[action_type] += count

    features = {
        'interview_preps': interview_preps,
        'cover_letters': cover_letters,
        'total_actions_today': total_actions,
        'action_breakdown': dict(action_breakdown),
    }

    # ── 9. News Feed ─────────────────────────────────────────────────────
    news_24h = NewsSnippet.objects.filter(created_at__gte=since)
    news_synced = news_24h.count()

    news_by_category = dict(
        news_24h
        .values_list('category')
        .annotate(c=Count('id'))
        .order_by('-c')
    )

    flagged_snippets = NewsSnippet.objects.filter(is_flagged=True, is_active=True).count()
    unapproved_snippets = NewsSnippet.objects.filter(is_approved=False, is_active=True).count()

    news = {
        'synced_today': news_synced,
        'by_category': news_by_category,
        'flagged': flagged_snippets,
        'unapproved': unapproved_snippets,
    }

    # ── 10. Notifications & Contact ──────────────────────────────────────
    notifs_24h = Notification.objects.filter(created_at__gte=since).count()
    unread_total = Notification.objects.filter(is_read=False).count()
    contact_submissions = ContactSubmission.objects.filter(created_at__gte=since).count()

    notifications = {
        'created_today': notifs_24h,
        'unread_total': unread_total,
        'contact_submissions': contact_submissions,
    }

    # ── 11. Infrastructure ───────────────────────────────────────────────
    from analyzer.models import CrawlSource
    stale_crawl_sources = CrawlSource.objects.filter(
        is_active=True,
        last_crawled_at__lt=since,
    ).count()
    total_crawl_sources = CrawlSource.objects.filter(is_active=True).count()

    infra = {
        'stale_crawl_sources': stale_crawl_sources,
        'total_crawl_sources': total_crawl_sources,
    }

    # ── Compose ──────────────────────────────────────────────────────────
    report_time_ist = now + IST_OFFSET

    return {
        'report_time_ist': report_time_ist.strftime('%d %b %Y, %I:%M %p IST'),
        'period': 'Last 24 hours',
        'users': users,
        'revenue': revenue,
        'credits': credits,
        'analyses': analyses,
        'resumes': resumes,
        'llm': llm,
        'job_alerts': job_alerts,
        'features': features,
        'news': news,
        'notifications': notifications,
        'infra': infra,
    }
