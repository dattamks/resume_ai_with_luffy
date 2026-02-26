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
        'description': 'Sent when a user requests a password reset via POST /api/auth/forgot-password/.',
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
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">{{ app_name }}</h1>
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
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 {{ app_name }}. All rights reserved.</p>
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

— {{ app_name }}''',
    },
    {
        'slug': 'welcome',
        'name': 'Welcome Email',
        'category': 'auth',
        'description': 'Sent when a new user registers via POST /api/auth/register/.',
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
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">{{ app_name }}</h1>
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
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 {{ app_name }}. All rights reserved.</p>
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

— {{ app_name }}''',
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
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">{{ app_name }}</h1>
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
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 {{ app_name }}. All rights reserved.</p>
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

— {{ app_name }}''',
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
              <h1 style="margin:0;color:#fff;font-size:24px;font-weight:700;">{{ app_name }}</h1>
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
              <p style="margin:0;color:#9a9ab0;font-size:12px;">&copy; 2026 {{ app_name }}. All rights reserved.</p>
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

— {{ app_name }}''',
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
