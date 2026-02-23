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
