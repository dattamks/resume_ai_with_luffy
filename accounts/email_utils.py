"""
Utility for sending templated emails using EmailTemplate model.

Usage:
    from accounts.email_utils import send_templated_email

    send_templated_email(
        slug='password-reset',
        recipient='user@example.com',
        context={'username': 'john', 'reset_link': 'https://...'},
    )
"""

import logging
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Template, Context

logger = logging.getLogger('accounts')


class EmailTemplateNotFound(Exception):
    """Raised when the requested email template slug does not exist or is inactive."""
    pass


def strip_html(html: str) -> str:
    """Minimal HTML-to-plaintext converter (no external deps)."""
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)  # strip remaining tags
    text = re.sub(r'\n{3,}', '\n\n', text)  # collapse excessive newlines
    return text.strip()


def send_templated_email(
    slug: str,
    recipient: str | list[str],
    context: dict | None = None,
    from_email: str | None = None,
    fail_silently: bool = False,
) -> bool:
    """
    Send an email using a stored EmailTemplate.

    Args:
        slug:           Unique slug of the EmailTemplate (e.g., 'password-reset').
        recipient:      Email address or list of addresses.
        context:        Dict of template variables (e.g., {'username': 'john'}).
        from_email:     Override the sender (defaults to DEFAULT_FROM_EMAIL).
        fail_silently:  If True, swallow exceptions instead of raising.

    Returns:
        True if the email was sent successfully, False otherwise.

    Raises:
        EmailTemplateNotFound: If no active template with the given slug exists.
    """
    from .models import EmailTemplate  # avoid circular import

    try:
        template = EmailTemplate.objects.get(slug=slug, is_active=True)
    except EmailTemplate.DoesNotExist:
        msg = f"Email template '{slug}' not found or inactive."
        logger.error(msg)
        if fail_silently:
            return False
        raise EmailTemplateNotFound(msg)

    # Build context with common defaults
    ctx = {
        'app_name': 'i-Luffy',
        'frontend_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:5173'),
        'support_email': getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
    }
    if context:
        ctx.update(context)

    template_context = Context(ctx)

    # Render subject + body via Django's template engine
    rendered_subject = Template(template.subject).render(template_context).strip()
    rendered_html = Template(template.html_body).render(template_context)

    # Plain-text: use explicit plain_text_body if provided, else auto-strip HTML
    if template.plain_text_body.strip():
        rendered_plain = Template(template.plain_text_body).render(template_context)
    else:
        rendered_plain = strip_html(rendered_html)

    # Normalize recipient to list
    if isinstance(recipient, str):
        recipient = [recipient]

    sender = from_email or settings.DEFAULT_FROM_EMAIL

    try:
        email = EmailMultiAlternatives(
            subject=rendered_subject,
            body=rendered_plain,
            from_email=sender,
            to=recipient,
        )
        email.attach_alternative(rendered_html, 'text/html')
        email.send(fail_silently=False)

        logger.info('Templated email sent: slug=%s, to=%s', slug, recipient)
        return True

    except Exception as exc:
        logger.error('Failed to send templated email slug=%s to=%s: %s', slug, recipient, exc)
        if fail_silently:
            return False
        raise
