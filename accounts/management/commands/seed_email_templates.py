"""
Management command to seed default email templates.
Run:  python manage.py seed_email_templates
"""

from django.core.management.base import BaseCommand
from accounts.models import EmailTemplate


# ── Default templates ─────────────────────────────────────────────────────────

TEMPLATES = [
    {
        'slug': 'password-reset',
        'name': 'Password Reset',
        'category': 'auth',
        'description': 'Sent when a user requests a password reset via POST /api/v1/auth/forgot-password/.',
        'subject': '{{ app_name }} — Password Reset',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Password Reset</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
              <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Password Reset Request</h2>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Hi <strong>{{ username }}</strong>,
              </p>
              <p style="margin:0 0 24px;color:#4a4a68;font-size:15px;line-height:1.6;">
                We received a request to reset your password. Click the button below to choose a new password:
              </p>
              <!-- CTA Button -->
              <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto 24px;">
                <tr>
                  <td style="background-color:#1a56db;border-radius:6px;">
                    <a href="{{ reset_link }}" target="_blank" style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">
                      Reset Password
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:14px;line-height:1.6;">
                This link expires in <strong>{{ expiry_hours }} hour(s)</strong>. If you did not request this, you can safely ignore this email.
              </p>
              <p style="margin:0 0 8px;color:#9a9ab0;font-size:13px;">If the button doesn't work, copy and paste this URL:</p>
              <p style="margin:0;word-break:break-all;color:#1a56db;font-size:13px;">{{ reset_link }}</p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
                <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
                <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
                <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Password Reset

Hi {{ username }},

We received a request to reset your password. Click the link below to choose a new password:

{{ reset_link }}

This link expires in {{ expiry_hours }} hour(s). If you did not request this, you can safely ignore this email.

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    {
        'slug': 'welcome',
        'name': 'Welcome Email',
        'category': 'auth',
        'description': 'Sent when a new user registers via POST /api/v1/auth/register/.',
        'subject': 'Welcome to {{ app_name }}! 🎉',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
              <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Welcome aboard, {{ username }}! 🎉</h2>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Your account has been created successfully. You're all set to start optimizing your resume with AI-powered analysis.
              </p>
              <p style="margin:0 0 24px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Here's what you can do:
              </p>
              <ul style="margin:0 0 24px;padding-left:20px;color:#4a4a68;font-size:15px;line-height:1.8;">
                <li>Upload your resume &amp; paste a job description</li>
                <li>Get ATS score, keyword analysis &amp; section feedback</li>
                <li>Download a detailed PDF report</li>
                <li>Track your improvement over time</li>
              </ul>
              <!-- CTA Button -->
              <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto 24px;">
                <tr>
                  <td style="background-color:#1a56db;border-radius:6px;">
                    <a href="{{ frontend_url }}" target="_blank" style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">
                      Get Started
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
                <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
                <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
                <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
Welcome to {{ app_name }}! 🎉

Hi {{ username }},

Your account has been created successfully. You're all set to start optimizing your resume with AI-powered analysis.

Here's what you can do:
- Upload your resume & paste a job description
- Get ATS score, keyword analysis & section feedback
- Download a detailed PDF report
- Track your improvement over time

Get started: {{ frontend_url }}

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    {
        'slug': 'password-changed',
        'name': 'Password Changed Confirmation',
        'category': 'auth',
        'description': 'Sent after a user successfully changes their password.',
        'subject': '{{ app_name }} — Password Changed',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Password Changed</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
              <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Password Changed</h2>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Hi <strong>{{ username }}</strong>,
              </p>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Your password was successfully changed on <strong>{{ changed_at }}</strong>.
              </p>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                If you did not make this change, please reset your password immediately or contact support.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
                <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
                <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
                <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Password Changed

Hi {{ username }},

Your password was successfully changed on {{ changed_at }}.

If you did not make this change, please reset your password immediately or contact support.

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    # ── Analysis Complete ────────────────────────────────────────────────────
    {
        'slug': 'analysis-complete',
        'name': 'Analysis Complete',
        'category': 'transactional',
        'description': 'Sent when an analysis finishes processing (respects feature_updates_email pref).',
        'subject': '{{ app_name }} — Your Resume Analysis is Ready',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr><td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
            <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
          </td></tr>
          <tr><td style="padding:40px;">
            <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Your Analysis is Ready!</h2>
            <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
              Hi <strong>{{ username }}</strong>,
            </p>
            <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
              Your resume analysis for <strong>{{ role }}</strong>{% if company %} at <strong>{{ company }}</strong>{% endif %} is complete.
            </p>
            <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
              <tr>
                <td style="padding:8px 16px;background:#e8f5e9;border-radius:6px;">
                  <span style="font-size:20px;font-weight:700;color:#2e7d32;">Grade: {{ grade }}</span>
                </td>
                <td style="padding:8px 16px;background:#e3f2fd;border-radius:6px;margin-left:12px;">
                  <span style="font-size:20px;font-weight:700;color:#1565c0;">ATS: {{ ats_score }}%</span>
                </td>
              </tr>
            </table>
            <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto 24px;">
              <tr><td style="background-color:#1a56db;border-radius:6px;">
                <a href="{{ frontend_url }}/analyses/{{ analysis_id }}" target="_blank" style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">
                  View Full Analysis
                </a>
              </td></tr>
            </table>
          </td></tr>
          <tr><td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
            <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
            <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
            <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
              <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
              <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
              <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
            </p>
          </td></tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Your Resume Analysis is Ready

Hi {{ username }},

Your resume analysis for {{ role }}{% if company %} at {{ company }}{% endif %} is complete.

Grade: {{ grade }}
ATS Score: {{ ats_score }}%

View full analysis: {{ frontend_url }}/analyses/{{ analysis_id }}

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    # ── Weekly Digest ─────────────────────────────────────────────────────────
    {
        'slug': 'weekly-digest',
        'name': 'Weekly Digest',
        'category': 'transactional',
        'description': 'Sent every Monday at 9 AM UTC summarising past week activity (respects newsletters_email pref).',
        'subject': '{{ app_name }} — Your Weekly Summary',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr><td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
            <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
          </td></tr>
          <tr><td style="padding:40px;">
            <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Your Weekly Summary</h2>
            <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
              Hi <strong>{{ username }}</strong>, here's what happened this week:
            </p>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;border:1px solid #e8e8f0;border-radius:6px;overflow:hidden;">
              <tr>
                <td style="padding:16px 20px;border-bottom:1px solid #e8e8f0;">
                  <strong style="color:#1a1a2e;">Analyses completed:</strong>
                  <span style="float:right;color:#4a4a68;">{{ analyses_count }}</span>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 20px;border-bottom:1px solid #e8e8f0;">
                  <strong style="color:#1a1a2e;">Average ATS score:</strong>
                  <span style="float:right;color:#4a4a68;">{{ avg_ats }}%</span>
                </td>
              </tr>
              {% if best_role %}
              <tr>
                <td style="padding:16px 20px;">
                  <strong style="color:#1a1a2e;">Best match:</strong>
                  <span style="float:right;color:#2e7d32;">{{ best_role }} ({{ best_score }}%)</span>
                </td>
              </tr>
              {% endif %}
            </table>
            <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto;">
              <tr><td style="background-color:#1a56db;border-radius:6px;">
                <a href="{{ frontend_url }}/dashboard" target="_blank" style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">
                  View Dashboard
                </a>
              </td></tr>
            </table>
          </td></tr>
          <tr><td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
            <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
            <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
            <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
              <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
              <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
              <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
            </p>
          </td></tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Your Weekly Summary

Hi {{ username }},

Here's your activity for the past week:

- Analyses completed: {{ analyses_count }}
- Average ATS score: {{ avg_ats }}%
{% if best_role %}- Best match: {{ best_role }} ({{ best_score }}%){% endif %}

View your dashboard: {{ frontend_url }}/dashboard

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    # ── Phase 11: Smart Job Alerts ────────────────────────────────────────────
    {
        'slug': 'job-alert-digest',
        'name': 'Job Alert Digest',
        'subject': '{{ matches_count }} new job match{% if matches_count != 1 %}es{% endif %} for your {{ frequency }} alert',
        'is_active': True,
        'html_body': '''\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:Helvetica Neue,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a1a4e 0%,#3d3d9e 100%);padding:32px 40px;">
              <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
              <p style="margin:8px 0 0;color:#c8c8f0;font-size:14px;">Smart Job Alerts</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px 40px;">
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Hi <strong>{{ username }}</strong>,
              </p>
              <p style="margin:0 0 24px;color:#4a4a68;font-size:15px;line-height:1.6;">
                We found <strong>{{ matches_count }} new job match{% if matches_count != 1 %}es{% endif %}</strong> for your {{ frequency }} alert. Here are the top results:
              </p>
              {% for job in matches %}
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;border:1px solid #e8e8f0;border-radius:6px;overflow:hidden;">
                <tr>
                  <td style="padding:16px 20px;">
                    <p style="margin:0 0 4px;font-size:16px;font-weight:700;color:#1a1a4e;">
                      <a href="{{ job.url }}" style="color:#1a1a4e;text-decoration:none;">{{ job.title }}</a>
                    </p>
                    <p style="margin:0 0 8px;font-size:14px;color:#6b6b8e;">{{ job.company }}{% if job.location %} · {{ job.location }}{% endif %}{% if job.salary %} · {{ job.salary }}{% endif %}</p>
                    <p style="margin:0 0 12px;font-size:13px;color:#4a4a68;line-height:1.5;">{{ job.reason }}</p>
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="background:#e8f5e9;border-radius:12px;padding:4px 12px;">
                          <span style="font-size:13px;font-weight:700;color:#2e7d32;">{{ job.score }}% match</span>
                        </td>
                        <td style="padding-left:12px;">
                          <a href="{{ job.url }}" style="font-size:13px;color:#3d3d9e;text-decoration:none;font-weight:600;">View job →</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              {% endfor %}
              <p style="margin:24px 0 0;text-align:center;">
                <a href="{{ frontend_url }}/job-alerts/{{ alert_id }}/"
                   style="display:inline-block;background:#1a1a4e;color:#fff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">
                  View All Matches
                </a>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
                <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
                <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
                <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
              </p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;">
                <a href="{{ frontend_url }}/job-alerts/{{ alert_id }}/" style="color:#9a9ab0;">Manage alert preferences</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Job Alert Digest

Hi {{ username }},

We found {{ matches_count }} new job match{% if matches_count != 1 %}es{% endif %} for your {{ frequency }} alert.

{% for job in matches %}
{{ job.title }} @ {{ job.company }}{% if job.location %} ({{ job.location }}){% endif %}
Match score: {{ job.score }}%
Why: {{ job.reason }}
Apply: {{ job.url }}

{% endfor %}

View all matches: {{ frontend_url }}/job-alerts/{{ alert_id }}/

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    {
        'slug': 'email-verification',
        'name': 'Email Verification',
        'category': 'auth',
        'description': 'Sent when a new user registers to verify their email address.',
        'subject': '{{ app_name }} — Verify Your Email Address',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verify Email</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:#1a56db;padding:30px 40px;text-align:center;">
              <a href="https://iluffy.in" target="_blank" style="text-decoration:none;"><img src="https://iluffy.in/logo.png" alt="{{ app_name }}" width="140" style="display:block;margin:0 auto;max-width:140px;height:auto;" /></a>
            </td>
          </tr>
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">Verify Your Email Address</h2>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Hi <strong>{{ username }}</strong>,
              </p>
              <p style="margin:0 0 24px;color:#4a4a68;font-size:15px;line-height:1.6;">
                Thanks for signing up! Please verify your email address by clicking the button below:
              </p>
              <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto 24px;">
                <tr>
                  <td style="background-color:#1a56db;border-radius:6px;">
                    <a href="{{ verify_url }}" target="_blank" style="display:inline-block;padding:14px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">
                      Verify Email
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 16px;color:#4a4a68;font-size:14px;line-height:1.6;">
                This link expires in <strong>24 hours</strong>. If you did not create this account, you can safely ignore this email.
              </p>
              <p style="margin:0 0 8px;color:#9a9ab0;font-size:13px;">If the button doesn't work, copy and paste this URL:</p>
              <p style="margin:0;word-break:break-all;color:#1a56db;font-size:13px;">{{ verify_url }}</p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#f4f4f7;padding:24px 40px;text-align:center;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. All rights reserved.</p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:12px;"><a href="https://iluffy.in" style="color:#1a56db;text-decoration:none;">iluffy.in</a></p>
              <p style="margin:8px 0 0;color:#9a9ab0;font-size:11px;">
                <a href="https://iluffy.in/privacy" style="color:#9a9ab0;text-decoration:none;">Privacy</a> &middot;
                <a href="https://iluffy.in/terms" style="color:#9a9ab0;text-decoration:none;">Terms</a> &middot;
                <a href="https://iluffy.in/data-usage" style="color:#9a9ab0;text-decoration:none;">Data Usage</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Verify Your Email Address

Hi {{ username }},

Thanks for signing up! Please verify your email address by clicking the link below:

{{ verify_url }}

This link expires in 24 hours. If you did not create this account, you can safely ignore this email.

— {{ app_name }}
https://iluffy.in

Privacy: https://iluffy.in/privacy | Terms: https://iluffy.in/terms''',
    },
    {
        'slug': 'admin-daily-digest',
        'name': 'Admin Daily Digest',
        'category': 'admin',
        'description': 'Sent twice daily (9 AM + 11 PM IST) to ADMIN_DIGEST_EMAILS with platform metrics.',
        'subject': '{{ app_name }} Admin Digest — {{ report_time_ist }}',
        'html_body': '''\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin Daily Digest</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f7;">
    <tr>
      <td align="center" style="padding:24px 0;">
        <table role="presentation" width="680" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a56db 0%,#0f3a8e 100%);padding:24px 32px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">i-Luffy Admin Digest</h1>
              <p style="margin:6px 0 0;color:#c7d7f5;font-size:13px;">{{ report_time_ist }} &middot; {{ period }}</p>
            </td>
          </tr>

          <tr><td style="padding:0 32px;">

          <!-- ━━ 1. Users & Signups ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #1a56db;padding-bottom:6px;">
                <h2 style="margin:0;color:#1a56db;font-size:16px;">1. Users &amp; Signups</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="25%" style="padding:8px 12px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:24px;font-weight:700;color:#1a56db;">{{ new_signups }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">New Signups</div>
              </td>
              <td width="4%"></td>
              <td width="25%" style="padding:8px 12px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:24px;font-weight:700;color:#1a56db;">{{ total_users }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Total Users</div>
              </td>
              <td width="4%"></td>
              <td width="25%" style="padding:8px 12px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:24px;font-weight:700;color:#1a56db;">{{ dau }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">DAU (today)</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 2. Revenue & Payments ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #059669;padding-bottom:6px;">
                <h2 style="margin:0;color:#059669;font-size:16px;">2. Revenue &amp; Payments</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="30%" style="padding:8px 12px;background:#ecfdf5;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#059669;">&#8377;{{ captured_total_inr }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Revenue ({{ captured_count }} payments)</div>
              </td>
              <td width="4%"></td>
              <td width="20%" style="padding:8px 12px;background:#fef2f2;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#dc2626;">{{ failed_payments }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Failed</div>
              </td>
              <td width="4%"></td>
              <td width="20%" style="padding:8px 12px;background:#ecfdf5;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#059669;">{{ new_subscriptions }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">New Subs</div>
              </td>
              <td width="4%"></td>
              <td width="18%" style="padding:8px 12px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#1a56db;">{{ webhooks_received }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Webhooks</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 3. Credit Economy ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #7c3aed;padding-bottom:6px;">
                <h2 style="margin:0;color:#7c3aed;font-size:16px;">3. Credit Economy</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;font-size:13px;color:#374151;">
            <tr>
              <td style="padding:6px 0;border-bottom:1px solid #f3f4f6;">Plan credits granted</td>
              <td style="padding:6px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;color:#059669;">+{{ plan_credits_granted }}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;border-bottom:1px solid #f3f4f6;">Top-up credits</td>
              <td style="padding:6px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;color:#059669;">+{{ topup_credits }}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;border-bottom:1px solid #f3f4f6;">Credits consumed</td>
              <td style="padding:6px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;color:#dc2626;">-{{ credits_consumed }}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;border-bottom:1px solid #f3f4f6;">Refunded</td>
              <td style="padding:6px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;color:#f59e0b;">+{{ credits_refunded }}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;">Users at zero balance</td>
              <td style="padding:6px 0;text-align:right;font-weight:600;color:#6b7280;">{{ zero_balance_users }}</td>
            </tr>
          </table>

          <!-- ━━ 4. Resume Analyses ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #ea580c;padding-bottom:6px;">
                <h2 style="margin:0;color:#ea580c;font-size:16px;">4. Resume Analyses</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="16%" style="padding:8px 6px;background:#fff7ed;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#ea580c;">{{ analyses_total }}</div>
                <div style="font-size:10px;color:#6b7280;">Total</div>
              </td>
              <td width="3%"></td>
              <td width="16%" style="padding:8px 6px;background:#ecfdf5;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#059669;">{{ analyses_done }}</div>
                <div style="font-size:10px;color:#6b7280;">Done</div>
              </td>
              <td width="3%"></td>
              <td width="16%" style="padding:8px 6px;background:#fef2f2;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#dc2626;">{{ analyses_failed }}</div>
                <div style="font-size:10px;color:#6b7280;">Failed</div>
              </td>
              <td width="3%"></td>
              <td width="18%" style="padding:8px 6px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#1a56db;">{{ avg_ats_score }}</div>
                <div style="font-size:10px;color:#6b7280;">Avg ATS</div>
              </td>
              <td width="3%"></td>
              <td width="18%" style="padding:8px 6px;background:#f0f5ff;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#1a56db;">{{ avg_overall_grade }}</div>
                <div style="font-size:10px;color:#6b7280;">Avg Grade</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 5. Resume Uploads & Generation ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #0891b2;padding-bottom:6px;">
                <h2 style="margin:0;color:#0891b2;font-size:16px;">5. Resumes &amp; Builder</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="30%" style="padding:8px 12px;background:#ecfeff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#0891b2;">{{ resumes_uploaded }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Uploaded</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#ecfeff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#0891b2;">{{ resumes_generated }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Generated</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#ecfeff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#0891b2;">{{ builder_sessions }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Builder Sessions</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 6. LLM Usage & Cost ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #be185d;padding-bottom:6px;">
                <h2 style="margin:0;color:#be185d;font-size:16px;">6. LLM Usage &amp; Cost</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="22%" style="padding:8px 8px;background:#fdf2f8;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#be185d;">{{ llm_total_calls }}</div>
                <div style="font-size:10px;color:#6b7280;">Calls</div>
              </td>
              <td width="3%"></td>
              <td width="22%" style="padding:8px 8px;background:#fdf2f8;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#be185d;">{{ llm_total_tokens }}</div>
                <div style="font-size:10px;color:#6b7280;">Tokens</div>
              </td>
              <td width="3%"></td>
              <td width="22%" style="padding:8px 8px;background:#fdf2f8;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#be185d;">${{ llm_cost_usd }}</div>
                <div style="font-size:10px;color:#6b7280;">Cost</div>
              </td>
              <td width="3%"></td>
              <td width="22%" style="padding:8px 8px;background:#fef2f2;border-radius:6px;text-align:center;">
                <div style="font-size:20px;font-weight:700;color:#dc2626;">{{ llm_failure_rate }}%</div>
                <div style="font-size:10px;color:#6b7280;">Fail Rate</div>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;font-size:12px;color:#6b7280;">
            <tr>
              <td>Avg duration: {{ llm_avg_duration }}s &middot; Failed: {{ llm_failed }}</td>
            </tr>
          </table>

          <!-- ━━ 7. Job Alerts & Matching ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #4f46e5;padding-bottom:6px;">
                <h2 style="margin:0;color:#4f46e5;font-size:16px;">7. Job Alerts &amp; Matching</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;font-size:13px;color:#374151;">
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Alert runs</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ alert_runs }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Jobs discovered</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ jobs_discovered }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Jobs matched</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ jobs_matched }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">New discovered jobs (DB)</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ new_discovered_jobs }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Avg relevance score</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ avg_relevance_score }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Alerts sent (email / in-app)</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ alerts_sent_email }} / {{ alerts_sent_in_app }}</td>
            </tr>
            <tr>
              <td style="padding:5px 0;">Active alerts (total)</td>
              <td style="padding:5px 0;text-align:right;font-weight:600;">{{ active_alerts_total }}</td>
            </tr>
          </table>

          <!-- ━━ 8. Feature Usage ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #d97706;padding-bottom:6px;">
                <h2 style="margin:0;color:#d97706;font-size:16px;">8. Feature Usage</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="30%" style="padding:8px 12px;background:#fffbeb;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#d97706;">{{ interview_preps }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Interview Preps</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#fffbeb;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#d97706;">{{ cover_letters }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Cover Letters</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#fffbeb;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#d97706;">{{ total_actions_today }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Total Actions</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 9. News Feed ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #0d9488;padding-bottom:6px;">
                <h2 style="margin:0;color:#0d9488;font-size:16px;">9. News Feed (Crawler)</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="30%" style="padding:8px 12px;background:#f0fdfa;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#0d9488;">{{ news_synced }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Synced Today</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#fef2f2;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#dc2626;">{{ news_flagged }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Flagged</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#fffbeb;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#d97706;">{{ news_unapproved }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Unapproved</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 10. Notifications & Contact ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #6366f1;padding-bottom:6px;">
                <h2 style="margin:0;color:#6366f1;font-size:16px;">10. Notifications &amp; Contact</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
            <tr>
              <td width="30%" style="padding:8px 12px;background:#eef2ff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#6366f1;">{{ notifications_created }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Created Today</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#eef2ff;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#6366f1;">{{ unread_total }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Unread (all)</div>
              </td>
              <td width="4%"></td>
              <td width="30%" style="padding:8px 12px;background:#fef2f2;border-radius:6px;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#dc2626;">{{ contact_submissions }}</div>
                <div style="font-size:11px;color:#6b7280;margin-top:2px;">Contact Forms</div>
              </td>
            </tr>
          </table>

          <!-- ━━ 11. Infrastructure ━━ -->
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
            <tr>
              <td style="border-bottom:2px solid #64748b;padding-bottom:6px;">
                <h2 style="margin:0;color:#64748b;font-size:16px;">11. Infrastructure</h2>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;font-size:13px;color:#374151;">
            <tr>
              <td style="padding:5px 0;border-bottom:1px solid #f3f4f6;">Stale crawl sources (not crawled in 24h)</td>
              <td style="padding:5px 0;text-align:right;border-bottom:1px solid #f3f4f6;font-weight:600;">{{ stale_crawl_sources }} / {{ total_crawl_sources }}</td>
            </tr>
          </table>

          </td></tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f4f4f7;padding:20px 32px;text-align:center;margin-top:24px;">
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 <a href="https://iluffy.in" style="color:#9a9ab0;text-decoration:none;">{{ app_name }}</a>. Admin Digest.</p>
              <p style="margin:6px 0 0;color:#9a9ab0;font-size:11px;">This email is sent twice daily (9 AM &amp; 11 PM IST) to platform administrators.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>''',
        'plain_text_body': '''\
{{ app_name }} — Admin Daily Digest
{{ report_time_ist }} | {{ period }}
================================================

1. USERS & SIGNUPS
  New signups: {{ new_signups }}
  Total users: {{ total_users }}
  DAU (today): {{ dau }}

2. REVENUE & PAYMENTS
  Revenue: INR {{ captured_total_inr }} ({{ captured_count }} captured)
  Failed payments: {{ failed_payments }}
  New subscriptions: {{ new_subscriptions }}
  Webhooks received: {{ webhooks_received }}

3. CREDIT ECONOMY
  Plan credits granted: +{{ plan_credits_granted }}
  Top-up credits: +{{ topup_credits }}
  Credits consumed: -{{ credits_consumed }}
  Refunded: +{{ credits_refunded }}
  Users at zero balance: {{ zero_balance_users }}

4. RESUME ANALYSES
  Total: {{ analyses_total }}
  Done: {{ analyses_done }} | Failed: {{ analyses_failed }}
  Avg ATS: {{ avg_ats_score }} | Avg Grade: {{ avg_overall_grade }}

5. RESUMES & BUILDER
  Uploaded: {{ resumes_uploaded }}
  Generated: {{ resumes_generated }}
  Builder sessions: {{ builder_sessions }}

6. LLM USAGE & COST
  Calls: {{ llm_total_calls }}
  Tokens: {{ llm_total_tokens }} (prompt: {{ llm_prompt_tokens }}, completion: {{ llm_completion_tokens }})
  Cost: ${{ llm_cost_usd }}
  Failure rate: {{ llm_failure_rate }}% ({{ llm_failed }} failed)
  Avg duration: {{ llm_avg_duration }}s

7. JOB ALERTS & MATCHING
  Alert runs: {{ alert_runs }}
  Jobs discovered: {{ jobs_discovered }}
  Jobs matched: {{ jobs_matched }}
  New discovered jobs: {{ new_discovered_jobs }}
  Avg relevance: {{ avg_relevance_score }}
  Alerts sent: {{ alerts_sent_email }} email, {{ alerts_sent_in_app }} in-app
  Active alerts: {{ active_alerts_total }}

8. FEATURE USAGE
  Interview preps: {{ interview_preps }}
  Cover letters: {{ cover_letters }}
  Total actions today: {{ total_actions_today }}

9. NEWS FEED (CRAWLER)
  Synced today: {{ news_synced }}
  Flagged: {{ news_flagged }}
  Unapproved: {{ news_unapproved }}

10. NOTIFICATIONS & CONTACT
  Created today: {{ notifications_created }}
  Unread (all): {{ unread_total }}
  Contact forms: {{ contact_submissions }}

11. INFRASTRUCTURE
  Stale crawl sources: {{ stale_crawl_sources }} / {{ total_crawl_sources }}

================================================
i-Luffy Admin Digest — sent twice daily (9 AM & 11 PM IST)''',
    },
]


class Command(BaseCommand):
    help = 'Seed default email templates (password-reset, welcome, password-changed)'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for tmpl_data in TEMPLATES:
            slug = tmpl_data['slug']
            obj, created = EmailTemplate.objects.update_or_create(
                slug=slug,
                defaults=tmpl_data,
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✅ Created: {obj.name} ({slug})'))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f'  🔄 Updated: {obj.name} ({slug})'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — {created_count} created, {updated_count} updated.'
        ))
