"""
Custom Prometheus metrics for Resume AI.

Usage:
    from resume_ai.metrics import (
        ANALYSIS_DURATION, LLM_TOKENS_USED, CREDIT_OPS,
        PAYMENT_FAILURES, CELERY_TASK_DURATION
    )

    # In analysis task:
    ANALYSIS_DURATION.labels(status='done').observe(elapsed_seconds)
    LLM_TOKENS_USED.labels(provider='openrouter', operation='analysis').inc(token_count)

    # In credit service:
    CREDIT_OPS.labels(operation='debit').inc()

    # In payment views:
    PAYMENT_FAILURES.labels(reason='verification_failed').inc()
"""

from prometheus_client import Counter, Histogram, Gauge

# ── Analysis Pipeline ────────────────────────────────────────────────────────

ANALYSIS_DURATION = Histogram(
    'resume_ai_analysis_duration_seconds',
    'Time spent on resume analysis (end-to-end)',
    labelnames=['status'],  # done, failed, cancelled
    buckets=[5, 10, 20, 30, 45, 60, 90, 120, 180, 300],
)

ANALYSIS_TOTAL = Counter(
    'resume_ai_analyses_total',
    'Total number of analyses started',
    labelnames=['status'],  # queued, done, failed
)

# ── LLM Usage ────────────────────────────────────────────────────────────────

LLM_TOKENS_USED = Counter(
    'resume_ai_llm_tokens_total',
    'Total LLM tokens consumed',
    labelnames=['provider', 'operation', 'token_type'],
    # provider: openrouter
    # operation: analysis, resume_generation, job_matching, cover_letter, interview_prep
    # token_type: prompt, completion
)

LLM_REQUESTS_TOTAL = Counter(
    'resume_ai_llm_requests_total',
    'Total LLM API calls',
    labelnames=['provider', 'operation', 'status'],
    # status: success, error, timeout, rate_limited
)

LLM_REQUEST_DURATION = Histogram(
    'resume_ai_llm_request_duration_seconds',
    'LLM API call duration',
    labelnames=['provider', 'operation'],
    buckets=[1, 2, 5, 10, 20, 30, 45, 60, 90, 120],
)

# ── Credits & Wallet ─────────────────────────────────────────────────────────

CREDIT_OPS = Counter(
    'resume_ai_credit_operations_total',
    'Credit operations performed',
    labelnames=['operation'],
    # operation: debit, refund, topup, plan_credit, admin_adjustment, upgrade_bonus
)

CREDIT_AMOUNT = Counter(
    'resume_ai_credit_amount_total',
    'Total credit amount by operation',
    labelnames=['operation'],
)

# ── Payments ──────────────────────────────────────────────────────────────────

PAYMENT_FAILURES = Counter(
    'resume_ai_payment_failures_total',
    'Payment failures by reason',
    labelnames=['reason'],
    # reason: verification_failed, razorpay_error, insufficient_credits, webhook_error
)

PAYMENT_SUCCESS = Counter(
    'resume_ai_payment_success_total',
    'Successful payments by type',
    labelnames=['payment_type'],  # subscription, topup
)

# ── Celery Tasks ──────────────────────────────────────────────────────────────

CELERY_TASK_DURATION = Histogram(
    'resume_ai_celery_task_duration_seconds',
    'Celery task execution duration',
    labelnames=['task_name', 'status'],  # status: success, failure, retry
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

CELERY_TASKS_TOTAL = Counter(
    'resume_ai_celery_tasks_total',
    'Total Celery tasks by name and outcome',
    labelnames=['task_name', 'status'],
)

# ── Resume Generation ────────────────────────────────────────────────────────

RESUME_GENERATION_TOTAL = Counter(
    'resume_ai_resume_generations_total',
    'Total resume generations',
    labelnames=['status', 'format'],  # status: done, failed; format: pdf, docx
)

# ── Job Alerts ────────────────────────────────────────────────────────────────

JOB_CRAWL_TOTAL = Counter(
    'resume_ai_job_crawl_total',
    'Total job crawl runs',
    labelnames=['status'],  # success, failed
)

JOB_MATCHES_FOUND = Counter(
    'resume_ai_job_matches_found_total',
    'Total job matches found across all alerts',
)

# ── Active Gauges ─────────────────────────────────────────────────────────────

ACTIVE_ANALYSES = Gauge(
    'resume_ai_active_analyses',
    'Currently running analyses',
)
