"""
Conversational Resume Builder — step orchestration & UI spec generation.

This module drives the guided resume-building chat. It:
1. Pre-fills resume data from profile/previous resume on session start
2. Generates structured UI specs for each step (buttons, chips, cards, etc.)
3. Processes user submissions and updates resume_data incrementally
4. Calls the LLM only for experience bullet structuring and final polish

Design principles:
- One question at a time (chat-style UX)
- Minimal typing — buttons, chips, selects wherever possible
- LLM calls kept to 1-2 per session (experience + final polish)
- UI spec is backend-driven: frontend is a dumb renderer
"""
import copy
import json
import logging
import re
import time
import uuid

from django.conf import settings
from django.contrib.auth.models import User

from ..models import (
    ResumeChat, ResumeChatMessage, Resume, ResumeAnalysis, GeneratedResume,
    LLMResponse, JobSearchProfile,
)

logger = logging.getLogger('analyzer')

# ── Common skill suggestions by industry ────────────────────────────────────

_INDUSTRY_SKILLS = {
    'technology': [
        'Python', 'JavaScript', 'TypeScript', 'React', 'Node.js', 'Django',
        'AWS', 'Docker', 'Kubernetes', 'PostgreSQL', 'Redis', 'Git',
        'CI/CD', 'REST APIs', 'Microservices', 'System Design', 'GraphQL',
        'Kafka', 'MongoDB', 'Linux',
    ],
    'finance': [
        'Excel', 'Python', 'SQL', 'Tableau', 'Financial Modeling',
        'Risk Analysis', 'Bloomberg', 'VBA', 'Power BI',
        'Regulatory Compliance', 'Data Analysis',
    ],
    'healthcare': [
        'EMR/EHR', 'HIPAA', 'Clinical Research', 'Data Analysis',
        'Patient Care', 'Medical Terminology', 'Epic', 'HL7/FHIR',
    ],
    'ecommerce': [
        'Python', 'JavaScript', 'React', 'Node.js', 'SQL',
        'Shopify', 'SEO', 'Google Analytics', 'A/B Testing',
        'Payment Integration', 'AWS', 'Elasticsearch',
    ],
    'education': [
        'Curriculum Design', 'LMS', 'EdTech', 'Assessment Design',
        'Student Engagement', 'Data Analysis', 'Google Workspace',
    ],
}

_EXPERIENCE_LEVELS = [
    {'id': 'entry', 'label': 'Entry Level (0-2 yrs)'},
    {'id': 'mid', 'label': 'Mid Level (3-5 yrs)'},
    {'id': 'senior', 'label': 'Senior (5-10 yrs)'},
    {'id': 'lead', 'label': 'Lead / Staff (10+ yrs)'},
    {'id': 'executive', 'label': 'Executive'},
]

_INDUSTRIES = [
    {'id': 'technology', 'label': 'Technology'},
    {'id': 'finance', 'label': 'Finance'},
    {'id': 'healthcare', 'label': 'Healthcare'},
    {'id': 'ecommerce', 'label': 'E-commerce'},
    {'id': 'education', 'label': 'Education'},
    {'id': 'other', 'label': 'Other'},
]


# ══════════════════════════════════════════════════════════════════════════════
# Session Initialization
# ══════════════════════════════════════════════════════════════════════════════

def start_session(user: User, source: str, base_resume_id: str = None) -> ResumeChat:
    """
    Create a new ResumeChat session and pre-fill resume_data based on source.

    All sessions are pure text chat. The source only determines what data
    is pre-filled before the conversation starts:
      - scratch:  empty — AI asks everything from zero
      - profile:  pre-fill from UserProfile + JobSearchProfile
      - previous: pre-fill from selected resume's analysis / generated data

    Args:
        user: The authenticated user.
        source: 'scratch', 'profile', or 'previous'.
        base_resume_id: UUID of Resume to use as base (for 'previous').

    Returns:
        The created ResumeChat instance with welcome message.
    """
    return start_text_session(user, source, base_resume_id)


def _empty_resume_data() -> dict:
    """Return the empty resume_data scaffold."""
    return {
        'contact': {
            'name': '',
            'email': '',
            'phone': '',
            'location': '',
            'linkedin': '',
            'portfolio': '',
        },
        'summary': '',
        'experience': [],
        'education': [],
        'skills': {
            'technical': [],
            'tools': [],
            'soft': [],
        },
        'certifications': [],
        'projects': [],
    }


def _prefill_from_profile(user: User, resume_data: dict) -> dict:
    """
    Pre-fill resume_data from UserProfile + JobSearchProfile.
    """
    contact = resume_data['contact']
    contact['name'] = f'{user.first_name} {user.last_name}'.strip() or user.username
    contact['email'] = user.email

    profile = getattr(user, 'profile', None)
    if profile:
        phone_parts = []
        if profile.country_code:
            phone_parts.append(profile.country_code)
        if profile.mobile_number:
            phone_parts.append(profile.mobile_number)
        contact['phone'] = ' '.join(phone_parts)
        contact['linkedin'] = profile.linkedin_url or ''
        contact['portfolio'] = profile.website_url or ''

    # Pull skills from latest JobSearchProfile
    latest_resume = Resume.objects.filter(user=user).order_by('-uploaded_at').first()
    if latest_resume:
        try:
            jsp = latest_resume.job_search_profile
            resume_data['skills']['technical'] = list(jsp.skills or [])
        except JobSearchProfile.DoesNotExist:
            pass

    return resume_data


def _prefill_from_resume(user: User, resume_id: str, resume_data: dict) -> dict:
    """
    Pre-fill resume_data from the best available source:
    1. GeneratedResume.resume_content (most refined)
    2. Resume.parsed_content (Phase A: extracted at upload time)
    3. ResumeAnalysis.parsed_content (legacy: extracted during analysis)
    4. Profile data (last resort)
    """
    _EXPECTED_KEYS = ('contact', 'summary', 'experience', 'education', 'skills', 'certifications', 'projects')

    def _ensure_keys(content):
        for key in _EXPECTED_KEYS:
            if key not in content:
                content[key] = _empty_resume_data()[key]
        return content

    # First try to find a GeneratedResume with resume_content for this resume
    if resume_id:
        try:
            resume = Resume.objects.get(id=resume_id, user=user)

            # Check for generated resumes linked to analyses of this resume
            gen = GeneratedResume.objects.filter(
                analysis__resume=resume,
                status=GeneratedResume.STATUS_DONE,
                resume_content__isnull=False,
            ).order_by('-created_at').first()

            if gen and gen.resume_content:
                return _ensure_keys(copy.deepcopy(gen.resume_content))

            # Phase A: prefer Resume.parsed_content (extracted at upload time)
            if resume.parsed_content:
                return _ensure_keys(copy.deepcopy(resume.parsed_content))

            # Legacy fallback: parsed_content from analysis
            analysis = ResumeAnalysis.objects.filter(
                resume=resume,
                user=user,
                status=ResumeAnalysis.STATUS_DONE,
                parsed_content__isnull=False,
            ).order_by('-created_at').first()

            if analysis and analysis.parsed_content:
                return _ensure_keys(copy.deepcopy(analysis.parsed_content))
        except Resume.DoesNotExist:
            pass

    # Also check for any generated resume by this user (any analysis)
    gen = GeneratedResume.objects.filter(
        user=user,
        status=GeneratedResume.STATUS_DONE,
        resume_content__isnull=False,
    ).order_by('-created_at').first()

    if gen and gen.resume_content:
        return _ensure_keys(copy.deepcopy(gen.resume_content))

    # Phase A: check any of user's resumes for parsed_content
    any_resume = Resume.objects.filter(
        user=user,
        parsed_content__isnull=False,
    ).order_by('-uploaded_at').first()

    if any_resume and any_resume.parsed_content:
        return _ensure_keys(copy.deepcopy(any_resume.parsed_content))

    # Legacy fallback: any analysis with parsed_content
    analysis = ResumeAnalysis.objects.filter(
        user=user,
        status=ResumeAnalysis.STATUS_DONE,
        parsed_content__isnull=False,
    ).order_by('-created_at').first()

    if analysis and analysis.parsed_content:
        return _ensure_keys(copy.deepcopy(analysis.parsed_content))

    # Fall back to profile
    return _prefill_from_profile(user, resume_data)


# ══════════════════════════════════════════════════════════════════════════════
# Step Processing — handles user submission and generates next step message
# ══════════════════════════════════════════════════════════════════════════════

def process_step(chat: ResumeChat, action: str, payload: dict = None) -> list:
    """
    Process a user action for the current step.

    1. Records the user's message
    2. Updates resume_data based on the action
    3. Advances to the next step (or handles edit/back)
    4. Generates the next assistant message with UI spec
    5. Returns list of new messages created

    Args:
        chat: The ResumeChat session.
        action: Action identifier (e.g., 'continue', 'skip', 'back', 'edit_card').
        payload: Additional data from the user (field values, selections, etc.).

    Returns:
        List of new ResumeChatMessage objects created.
    """
    payload = payload or {}
    new_messages = []

    # ── Handle back action for any step ──
    if action == 'back':
        user_msg = _add_user_message(chat, '← Back', action='back')
        new_messages.append(user_msg)
        chat.go_back()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        new_messages.append(assistant_msg)
        return new_messages

    # ── Dispatch to step handler ──
    handler = _STEP_HANDLERS.get(chat.current_step)
    if handler:
        new_messages = handler(chat, action, payload)
    else:
        # Unknown step — just advance
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        new_messages.append(assistant_msg)

    return new_messages


# ── Step handlers ────────────────────────────────────────────────────────────

def _handle_contact(chat, action, payload):
    """Process contact step submission."""
    messages = []

    if action == 'update_card':
        # User edited contact fields
        contact = chat.resume_data.get('contact', {})
        for key in ('name', 'email', 'phone', 'location', 'linkedin', 'portfolio'):
            if key in payload:
                contact[key] = payload[key]
        chat.resume_data['contact'] = contact
        chat.save(update_fields=['resume_data', 'updated_at'])

        user_msg = _add_user_message(chat, 'Contact info updated ✓', action='update_card')
        messages.append(user_msg)

        # Re-show the contact card with updates
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'continue':
        user_msg = _add_user_message(chat, 'Contact info confirmed ✓', action='continue')
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_target_role(chat, action, payload):
    """Process target role step."""
    messages = []

    if action == 'submit':
        chat.target_role = payload.get('target_role', '')
        chat.target_company = payload.get('target_company', '')
        chat.save(update_fields=['target_role', 'target_company', 'updated_at'])

        display = chat.target_role or 'Not specified'
        user_msg = _add_user_message(chat, f'Target: {display}', action='submit')
        messages.append(user_msg)

        # Now ask experience level
        assistant_msg = _build_message(chat, ResumeChat.STEP_TARGET_ROLE, _build_experience_level_ui(chat))
        messages.append(assistant_msg)

    elif action == 'select_level':
        level = payload.get('value', '')
        chat.experience_level = level
        chat.save(update_fields=['experience_level', 'updated_at'])

        label = next((l['label'] for l in _EXPERIENCE_LEVELS if l['id'] == level), level)
        user_msg = _add_user_message(chat, label, action='select_level')
        messages.append(user_msg)

        # Now ask industry
        assistant_msg = _build_message(chat, ResumeChat.STEP_TARGET_ROLE, _build_industry_ui(chat))
        messages.append(assistant_msg)

    elif action == 'select_industry':
        industry = payload.get('value', '')
        chat.target_industry = industry
        chat.save(update_fields=['target_industry', 'updated_at'])

        label = next((i['label'] for i in _INDUSTRIES if i['id'] == industry), industry)
        user_msg = _add_user_message(chat, f'Industry: {label}', action='select_industry')
        messages.append(user_msg)

        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action in ('skip', 'continue'):
        user_msg = _add_user_message(chat, 'Skipped targeting', action='skip')
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_experience_input(chat, action, payload):
    """Process experience input step — structured or free text."""
    messages = []

    if action == 'select_mode':
        mode = payload.get('value', 'structured')
        if mode == 'freetext':
            # Show textarea for pasting
            user_msg = _add_user_message(chat, 'I\'ll type/paste my experience', action='select_mode')
            messages.append(user_msg)
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, {
                'type': 'textarea',
                'message': 'Paste or type your work history below. Include company names, titles, dates, and what you accomplished. Don\'t worry about formatting — I\'ll structure everything.',
                'field': {
                    'key': 'experience_raw',
                    'label': 'Work History',
                    'placeholder': 'e.g., I worked at Acme Corp as a Senior Developer from Jan 2022 to present. I led the migration of our monolith to microservices, reducing deploy time by 60%...',
                },
                'actions': [
                    {'id': 'submit_raw', 'label': 'Structure with AI ✨', 'type': 'button', 'primary': True},
                    {'id': 'back', 'label': '← Back', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)
        else:
            # Show structured form
            user_msg = _add_user_message(chat, 'I\'ll fill in fields', action='select_mode')
            messages.append(user_msg)
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, _build_experience_form_ui())
            messages.append(assistant_msg)

    elif action == 'form_submit':
        # User submitted structured experience entry
        experience = chat.resume_data.get('experience', [])
        entry = {
            'title': payload.get('title', ''),
            'company': payload.get('company', ''),
            'location': payload.get('location', ''),
            'start_date': payload.get('start_date', ''),
            'end_date': payload.get('end_date', 'Present'),
            'bullets': [],
        }
        # Parse description into bullets
        desc = payload.get('description', '')
        if desc:
            entry['bullets'] = [b.strip().lstrip('•-*').strip() for b in desc.split('\n') if b.strip()]

        experience.append(entry)
        chat.resume_data['experience'] = experience
        chat.save(update_fields=['resume_data', 'updated_at'])

        user_msg = _add_user_message(
            chat,
            f'Added: {entry["title"]} @ {entry["company"]}',
            action='form_submit',
        )
        messages.append(user_msg)

        # Ask if they want to add more or continue
        assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, {
            'type': 'buttons',
            'message': 'Role added! Want to add another, or move on?',
            'buttons': [
                {'id': 'add_more', 'label': '+ Add Another Role', 'type': 'button'},
                {'id': 'done_experience', 'label': 'Continue to review ✓', 'type': 'button', 'primary': True},
            ],
        })
        messages.append(assistant_msg)

    elif action == 'add_more':
        user_msg = _add_user_message(chat, 'Adding another role', action='add_more')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, _build_experience_form_ui())
        messages.append(assistant_msg)

    elif action == 'submit_raw':
        # User pasted free text — call LLM to structure
        raw_text = payload.get('experience_raw', '')
        if not raw_text.strip():
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, {
                'type': 'textarea',
                'message': 'Please enter your work history first.',
                'field': {
                    'key': 'experience_raw',
                    'label': 'Work History',
                    'placeholder': 'e.g., I worked at Acme Corp as a Senior Developer...',
                },
                'actions': [
                    {'id': 'submit_raw', 'label': 'Structure with AI ✨', 'type': 'button', 'primary': True},
                    {'id': 'back', 'label': '← Back', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)
            return messages

        user_msg = _add_user_message(chat, raw_text[:100] + ('...' if len(raw_text) > 100 else ''), action='submit_raw')
        messages.append(user_msg)

        # LLM call to structure experience
        structured, llm_record = _llm_structure_experience(chat.user, raw_text, chat.target_role)
        chat.resume_data['experience'] = structured
        chat.save(update_fields=['resume_data', 'updated_at'])

        # Jump to experience review
        chat.current_step = ResumeChat.STEP_EXPERIENCE_REVIEW
        chat.save(update_fields=['current_step'])
        assistant_msg = _generate_step_message(chat, llm_response=llm_record)
        messages.append(assistant_msg)
        return messages

    elif action == 'done_experience':
        user_msg = _add_user_message(chat, 'Experience complete ✓', action='done_experience')
        messages.append(user_msg)
        # Jump to experience review
        chat.current_step = ResumeChat.STEP_EXPERIENCE_REVIEW
        chat.save(update_fields=['current_step'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_experience_review(chat, action, payload):
    """Process experience review — edit, rewrite, or continue."""
    messages = []

    if action == 'continue':
        user_msg = _add_user_message(chat, 'Experience confirmed ✓', action='continue')
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'edit_card':
        card_idx = payload.get('card_index', 0)
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            entry = experience[card_idx]
            user_msg = _add_user_message(chat, f'Editing: {entry.get("title", "")} @ {entry.get("company", "")}', action='edit_card')
            messages.append(user_msg)
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_REVIEW, {
                'type': 'buttons',
                'message': f'What would you like to do with **{entry.get("title", "")} @ {entry.get("company", "")}**?',
                'context': {'card_index': card_idx},
                'buttons': [
                    {'id': 'edit_fields', 'label': 'Edit title/company/dates', 'type': 'button'},
                    {'id': 'rewrite_ai', 'label': 'Rewrite bullets with AI ✨', 'type': 'button'},
                    {'id': 'add_bullets', 'label': 'Add more bullets', 'type': 'button'},
                    {'id': 'delete_card', 'label': 'Delete this role', 'type': 'button'},
                    {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)

    elif action == 'edit_fields':
        card_idx = payload.get('card_index', 0)
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            entry = experience[card_idx]
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_REVIEW, {
                'type': 'form_group',
                'message': 'Edit the fields below:',
                'context': {'card_index': card_idx},
                'fields': [
                    {'key': 'title', 'type': 'text', 'label': 'Job Title', 'value': entry.get('title', ''), 'required': True},
                    {'key': 'company', 'type': 'text', 'label': 'Company', 'value': entry.get('company', ''), 'required': True},
                    {'key': 'location', 'type': 'text', 'label': 'Location', 'value': entry.get('location', '')},
                    {'key': 'start_date', 'type': 'text', 'label': 'Start Date', 'value': entry.get('start_date', '')},
                    {'key': 'end_date', 'type': 'text', 'label': 'End Date', 'value': entry.get('end_date', 'Present')},
                ],
                'actions': [
                    {'id': 'save_edit', 'label': 'Save ✓', 'type': 'button', 'primary': True},
                    {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)

    elif action == 'save_edit':
        card_idx = payload.get('card_index', 0)
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            for key in ('title', 'company', 'location', 'start_date', 'end_date'):
                if key in payload:
                    experience[card_idx][key] = payload[key]
            chat.resume_data['experience'] = experience
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, 'Role updated ✓', action='save_edit')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'rewrite_ai':
        card_idx = payload.get('card_index', 0)
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            # Show focus options
            user_msg = _add_user_message(chat, 'Rewrite with AI', action='rewrite_ai')
            messages.append(user_msg)
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_REVIEW, {
                'type': 'multi_select_chips',
                'message': 'What should I focus the rewrite on?',
                'context': {'card_index': card_idx},
                'groups': [
                    {
                        'key': 'focus',
                        'label': 'Focus areas',
                        'chips': [
                            {'id': 'leadership', 'label': 'Leadership & management'},
                            {'id': 'technical', 'label': 'Technical achievements'},
                            {'id': 'impact', 'label': 'Quantified impact'},
                            {'id': 'ats', 'label': f'ATS keywords for {chat.target_role or "target role"}'},
                        ],
                    },
                ],
                'actions': [
                    {'id': 'do_rewrite', 'label': 'Rewrite →', 'type': 'button', 'primary': True},
                    {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)

    elif action == 'do_rewrite':
        card_idx = payload.get('card_index', 0)
        focus = payload.get('focus', [])
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            entry = experience[card_idx]
            user_msg = _add_user_message(chat, 'Rewriting...', action='do_rewrite')
            messages.append(user_msg)

            new_bullets, llm_record = _llm_rewrite_bullets(
                chat.user, entry, focus, chat.target_role,
            )
            experience[card_idx]['bullets'] = new_bullets
            chat.resume_data['experience'] = experience
            chat.save(update_fields=['resume_data', 'updated_at'])

            # Show result with accept/reject
            assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_REVIEW, {
                'type': 'card_list',
                'message': 'Here\'s the rewrite:',
                'cards': [_experience_to_card(experience[card_idx], card_idx)],
                'actions': [
                    {'id': 'cancel_edit', 'label': 'Keep this ✓', 'type': 'button', 'primary': True},
                    {'id': 'rewrite_ai', 'label': 'Try again', 'type': 'button'},
                ],
                'context': {'card_index': card_idx},
            }, llm_response=llm_record)
            messages.append(assistant_msg)

    elif action == 'add_bullets':
        card_idx = payload.get('card_index', 0)
        user_msg = _add_user_message(chat, 'Adding bullets', action='add_bullets')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_REVIEW, {
            'type': 'textarea',
            'message': 'Add more achievements (one per line):',
            'context': {'card_index': card_idx},
            'field': {
                'key': 'new_bullets',
                'label': 'Additional achievements',
                'placeholder': 'e.g., Reduced API response time by 40%\nMentored 3 junior developers',
            },
            'actions': [
                {'id': 'save_bullets', 'label': 'Add ✓', 'type': 'button', 'primary': True},
                {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
            ],
        })
        messages.append(assistant_msg)

    elif action == 'save_bullets':
        card_idx = payload.get('card_index', 0)
        new_text = payload.get('new_bullets', '')
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience) and new_text.strip():
            new_bullets = [b.strip().lstrip('•-*').strip() for b in new_text.split('\n') if b.strip()]
            experience[card_idx].setdefault('bullets', []).extend(new_bullets)
            chat.resume_data['experience'] = experience
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, f'Added {len(new_bullets)} bullet(s)', action='save_bullets')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'delete_card':
        card_idx = payload.get('card_index', 0)
        experience = chat.resume_data.get('experience', [])
        if 0 <= card_idx < len(experience):
            removed = experience.pop(card_idx)
            chat.resume_data['experience'] = experience
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(
                chat,
                f'Removed: {removed.get("title", "")} @ {removed.get("company", "")}',
                action='delete_card',
            )
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action in ('cancel_edit',):
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'add':
        user_msg = _add_user_message(chat, 'Adding a new role', action='add')
        messages.append(user_msg)
        # Go back to experience_input for adding
        chat.current_step = ResumeChat.STEP_EXPERIENCE_INPUT
        chat.save(update_fields=['current_step'])
        assistant_msg = _build_message(chat, ResumeChat.STEP_EXPERIENCE_INPUT, _build_experience_form_ui())
        messages.append(assistant_msg)

    return messages


def _handle_education(chat, action, payload):
    """Process education step."""
    messages = []

    if action == 'form_submit':
        education = chat.resume_data.get('education', [])
        entry = {
            'degree': payload.get('degree', ''),
            'institution': payload.get('institution', ''),
            'location': payload.get('location', ''),
            'year': payload.get('year', ''),
            'gpa': payload.get('gpa', ''),
        }
        education.append(entry)
        chat.resume_data['education'] = education
        chat.save(update_fields=['resume_data', 'updated_at'])

        user_msg = _add_user_message(
            chat,
            f'Added: {entry["degree"]} @ {entry["institution"]}',
            action='form_submit',
        )
        messages.append(user_msg)

        # Ask if more
        assistant_msg = _build_message(chat, ResumeChat.STEP_EDUCATION, {
            'type': 'buttons',
            'message': 'Education added! Want to add more?',
            'buttons': [
                {'id': 'add_more', 'label': '+ Add Another', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        })
        messages.append(assistant_msg)

    elif action == 'add_more':
        user_msg = _add_user_message(chat, 'Adding another', action='add_more')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_EDUCATION, _build_education_form_ui())
        messages.append(assistant_msg)

    elif action == 'edit_card':
        card_idx = payload.get('card_index', 0)
        edu = chat.resume_data.get('education', [])
        if 0 <= card_idx < len(edu):
            entry = edu[card_idx]
            assistant_msg = _build_message(chat, ResumeChat.STEP_EDUCATION, {
                'type': 'form_group',
                'message': 'Edit education:',
                'context': {'card_index': card_idx},
                'fields': [
                    {'key': 'degree', 'type': 'text', 'label': 'Degree', 'value': entry.get('degree', ''), 'required': True},
                    {'key': 'institution', 'type': 'text', 'label': 'Institution', 'value': entry.get('institution', ''), 'required': True},
                    {'key': 'location', 'type': 'text', 'label': 'Location', 'value': entry.get('location', '')},
                    {'key': 'year', 'type': 'text', 'label': 'Year', 'value': entry.get('year', '')},
                    {'key': 'gpa', 'type': 'text', 'label': 'GPA', 'value': entry.get('gpa', '')},
                ],
                'actions': [
                    {'id': 'save_edit', 'label': 'Save ✓', 'type': 'button', 'primary': True},
                    {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)

    elif action == 'save_edit':
        card_idx = payload.get('card_index', 0)
        education = chat.resume_data.get('education', [])
        if 0 <= card_idx < len(education):
            for key in ('degree', 'institution', 'location', 'year', 'gpa'):
                if key in payload:
                    education[card_idx][key] = payload[key]
            chat.resume_data['education'] = education
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, 'Education updated ✓', action='save_edit')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'delete_card':
        card_idx = payload.get('card_index', 0)
        education = chat.resume_data.get('education', [])
        if 0 <= card_idx < len(education):
            removed = education.pop(card_idx)
            chat.resume_data['education'] = education
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, f'Removed: {removed.get("degree", "")}', action='delete_card')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action in ('continue', 'skip'):
        label = 'Education confirmed ✓' if action == 'continue' else 'Skipped education'
        user_msg = _add_user_message(chat, label, action=action)
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'cancel_edit':
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_skills(chat, action, payload):
    """Process skills step — chip selection."""
    messages = []

    if action == 'chips':
        skills = payload.get('value', {})
        chat.resume_data['skills'] = {
            'technical': skills.get('technical', []),
            'tools': skills.get('tools', []),
            'soft': skills.get('soft', []),
        }
        chat.save(update_fields=['resume_data', 'updated_at'])

        total = sum(len(v) for v in chat.resume_data['skills'].values())
        user_msg = _add_user_message(chat, f'{total} skills selected ✓', action='chips')
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action in ('continue', 'skip'):
        user_msg = _add_user_message(chat, 'Skills confirmed ✓' if action == 'continue' else 'Skipped skills', action=action)
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_certifications(chat, action, payload):
    """Process certifications step."""
    messages = []

    if action == 'yes':
        user_msg = _add_user_message(chat, 'Adding certifications', action='yes')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_CERTIFICATIONS, _build_cert_form_ui())
        messages.append(assistant_msg)

    elif action == 'form_submit':
        certs = chat.resume_data.get('certifications', [])
        entry = {
            'name': payload.get('name', ''),
            'issuer': payload.get('issuer', ''),
            'year': payload.get('year', ''),
        }
        certs.append(entry)
        chat.resume_data['certifications'] = certs
        chat.save(update_fields=['resume_data', 'updated_at'])

        user_msg = _add_user_message(chat, f'Added: {entry["name"]}', action='form_submit')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_CERTIFICATIONS, {
            'type': 'buttons',
            'message': 'Certification added! Any more?',
            'buttons': [
                {'id': 'add_more', 'label': '+ Add Another', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        })
        messages.append(assistant_msg)

    elif action == 'add_more':
        user_msg = _add_user_message(chat, 'Adding another', action='add_more')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_CERTIFICATIONS, _build_cert_form_ui())
        messages.append(assistant_msg)

    elif action in ('no', 'skip', 'continue'):
        user_msg = _add_user_message(chat, 'No certifications' if action == 'no' else 'Certifications done ✓', action=action)
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_projects(chat, action, payload):
    """Process projects step."""
    messages = []

    if action == 'yes':
        user_msg = _add_user_message(chat, 'Adding projects', action='yes')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_PROJECTS, _build_project_form_ui())
        messages.append(assistant_msg)

    elif action == 'form_submit':
        projects = chat.resume_data.get('projects', [])
        techs_raw = payload.get('technologies', '')
        technologies = [t.strip() for t in techs_raw.split(',') if t.strip()] if isinstance(techs_raw, str) else techs_raw
        entry = {
            'name': payload.get('name', ''),
            'description': payload.get('description', ''),
            'technologies': technologies,
            'url': payload.get('url', ''),
        }
        projects.append(entry)
        chat.resume_data['projects'] = projects
        chat.save(update_fields=['resume_data', 'updated_at'])

        user_msg = _add_user_message(chat, f'Added: {entry["name"]}', action='form_submit')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_PROJECTS, {
            'type': 'buttons',
            'message': 'Project added! Any more?',
            'buttons': [
                {'id': 'add_more', 'label': '+ Add Another', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        })
        messages.append(assistant_msg)

    elif action == 'add_more':
        user_msg = _add_user_message(chat, 'Adding another', action='add_more')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_PROJECTS, _build_project_form_ui())
        messages.append(assistant_msg)

    elif action == 'edit_card':
        card_idx = payload.get('card_index', 0)
        projects = chat.resume_data.get('projects', [])
        if 0 <= card_idx < len(projects):
            entry = projects[card_idx]
            assistant_msg = _build_message(chat, ResumeChat.STEP_PROJECTS, {
                'type': 'form_group',
                'message': 'Edit project:',
                'context': {'card_index': card_idx},
                'fields': [
                    {'key': 'name', 'type': 'text', 'label': 'Project Name', 'value': entry.get('name', ''), 'required': True},
                    {'key': 'description', 'type': 'textarea', 'label': 'Description', 'value': entry.get('description', '')},
                    {'key': 'technologies', 'type': 'text', 'label': 'Technologies (comma-separated)', 'value': ', '.join(entry.get('technologies', []))},
                    {'key': 'url', 'type': 'text', 'label': 'URL', 'value': entry.get('url', '')},
                ],
                'actions': [
                    {'id': 'save_edit', 'label': 'Save ✓', 'type': 'button', 'primary': True},
                    {'id': 'cancel_edit', 'label': 'Cancel', 'type': 'button'},
                ],
            })
            messages.append(assistant_msg)

    elif action == 'save_edit':
        card_idx = payload.get('card_index', 0)
        projects = chat.resume_data.get('projects', [])
        if 0 <= card_idx < len(projects):
            for key in ('name', 'description', 'url'):
                if key in payload:
                    projects[card_idx][key] = payload[key]
            if 'technologies' in payload:
                techs_raw = payload['technologies']
                projects[card_idx]['technologies'] = [t.strip() for t in techs_raw.split(',') if t.strip()] if isinstance(techs_raw, str) else techs_raw
            chat.resume_data['projects'] = projects
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, 'Project updated ✓', action='save_edit')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'delete_card':
        card_idx = payload.get('card_index', 0)
        projects = chat.resume_data.get('projects', [])
        if 0 <= card_idx < len(projects):
            removed = projects.pop(card_idx)
            chat.resume_data['projects'] = projects
            chat.save(update_fields=['resume_data', 'updated_at'])
            user_msg = _add_user_message(chat, f'Removed: {removed.get("name", "")}', action='delete_card')
            messages.append(user_msg)
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action in ('no', 'skip', 'continue'):
        user_msg = _add_user_message(chat, 'No projects' if action == 'no' else 'Projects done ✓', action=action)
        messages.append(user_msg)
        chat.advance_step()
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'cancel_edit':
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    return messages


def _handle_review(chat, action, payload):
    """Process review step — AI polish and template selection."""
    messages = []

    if action == 'polish':
        # LLM call: generate summary, polish bullets, add ATS keywords
        user_msg = _add_user_message(chat, 'Polish my resume ✨', action='polish')
        messages.append(user_msg)

        polished_data, llm_record = _llm_polish_resume(chat)
        chat.resume_data = polished_data
        chat.save(update_fields=['resume_data', 'updated_at'])

        # Show polished preview + template picker
        assistant_msg = _build_message(chat, ResumeChat.STEP_REVIEW, {
            'type': 'preview',
            'message': 'Your resume is polished and ready! Review below and pick a template.',
            'resume_data': polished_data,
            'template_picker': _build_template_picker_data(),
            'actions': [
                {'id': 'back_to_edit', 'label': '← Go back and edit', 'type': 'button'},
                {'id': 'finalize', 'label': 'Generate Resume →', 'type': 'button', 'primary': True},
            ],
        }, llm_response=llm_record)
        messages.append(assistant_msg)

    elif action == 'back_to_edit':
        user_msg = _add_user_message(chat, 'Going back to edit', action='back_to_edit')
        messages.append(user_msg)
        # Go back to experience review as a sensible default
        chat.current_step = ResumeChat.STEP_EXPERIENCE_REVIEW
        chat.save(update_fields=['current_step', 'updated_at'])
        assistant_msg = _generate_step_message(chat)
        messages.append(assistant_msg)

    elif action == 'skip_polish':
        user_msg = _add_user_message(chat, 'Skip polish, go to template', action='skip_polish')
        messages.append(user_msg)
        assistant_msg = _build_message(chat, ResumeChat.STEP_REVIEW, {
            'type': 'preview',
            'message': 'Here\'s your resume. Pick a template to generate.',
            'resume_data': chat.resume_data,
            'template_picker': _build_template_picker_data(),
            'actions': [
                {'id': 'polish', 'label': '✨ Polish with AI first', 'type': 'button'},
                {'id': 'back_to_edit', 'label': '← Go back and edit', 'type': 'button'},
                {'id': 'finalize', 'label': 'Generate Resume →', 'type': 'button', 'primary': True},
            ],
        })
        messages.append(assistant_msg)

    return messages


# ── Handler registry ─────────────────────────────────────────────────────────

_STEP_HANDLERS = {
    ResumeChat.STEP_CONTACT: _handle_contact,
    ResumeChat.STEP_TARGET_ROLE: _handle_target_role,
    ResumeChat.STEP_EXPERIENCE_INPUT: _handle_experience_input,
    ResumeChat.STEP_EXPERIENCE_REVIEW: _handle_experience_review,
    ResumeChat.STEP_EDUCATION: _handle_education,
    ResumeChat.STEP_SKILLS: _handle_skills,
    ResumeChat.STEP_CERTIFICATIONS: _handle_certifications,
    ResumeChat.STEP_PROJECTS: _handle_projects,
    ResumeChat.STEP_REVIEW: _handle_review,
}


# ══════════════════════════════════════════════════════════════════════════════
# UI Spec Builders — generate the structured JSON for each step
# ══════════════════════════════════════════════════════════════════════════════

def _generate_step_message(chat, llm_response=None):
    """Generate the assistant message with UI spec for the current step."""
    step = chat.current_step
    builder = _STEP_UI_BUILDERS.get(step)
    if builder:
        ui_data = builder(chat)
    else:
        ui_data = {
            'type': 'buttons',
            'message': 'Something went wrong. Let\'s continue.',
            'buttons': [{'id': 'continue', 'label': 'Continue', 'type': 'button', 'primary': True}],
        }
    return _build_message(chat, step, ui_data, llm_response=llm_response)


def _build_message(chat, step, ui_data, llm_response=None):
    """Create and save an assistant message with the given UI spec."""
    message_text = ui_data.pop('message', '')
    return ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_ASSISTANT,
        content=message_text,
        ui_spec=ui_data,
        step=step,
        llm_response=llm_response,
    )


def _add_user_message(chat, content, action=''):
    """Create and save a user message."""
    return ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_USER,
        content=content,
        extracted_data={'action': action},
        step=chat.current_step,
    )


# ── Per-step UI builders ────────────────────────────────────────────────────

def _build_contact_ui(chat):
    """Build editable card UI for contact info."""
    contact = chat.resume_data.get('contact', {})
    fields = [
        {'key': 'name', 'label': 'Full Name', 'value': contact.get('name', ''), 'icon': '👤'},
        {'key': 'email', 'label': 'Email', 'value': contact.get('email', ''), 'icon': '✉️'},
        {'key': 'phone', 'label': 'Phone', 'value': contact.get('phone', ''), 'icon': '📱'},
        {'key': 'location', 'label': 'Location', 'value': contact.get('location', ''), 'icon': '📍'},
        {'key': 'linkedin', 'label': 'LinkedIn', 'value': contact.get('linkedin', ''), 'icon': '🔗'},
        {'key': 'portfolio', 'label': 'Portfolio / Website', 'value': contact.get('portfolio', ''), 'icon': '🌐'},
    ]
    has_data = any(f['value'] for f in fields)
    if has_data:
        return {
            'type': 'editable_card',
            'message': 'Here\'s your contact info. Tap any field to edit, or confirm to continue.',
            'fields': fields,
            'editable': True,
            'actions': [
                {'id': 'update_card', 'label': '✏️ Save Changes', 'type': 'button'},
                {'id': 'continue', 'label': 'Looks good ✓', 'type': 'button', 'primary': True},
            ],
        }
    else:
        return {
            'type': 'editable_card',
            'message': 'Let\'s start with your contact information. Fill in the fields below.',
            'fields': fields,
            'editable': True,
            'actions': [
                {'id': 'update_card', 'label': '✏️ Save', 'type': 'button', 'primary': True},
            ],
        }


def _build_target_role_ui(chat):
    """Build text input UI for target role."""
    return {
        'type': 'text_input',
        'message': 'What role are you targeting? (This helps tailor your resume. You can skip this.)',
        'field': {
            'key': 'target_role',
            'label': 'Target Role',
            'value': chat.target_role,
            'placeholder': 'e.g., Senior Backend Developer',
        },
        'secondary_field': {
            'key': 'target_company',
            'label': 'Target Company (optional)',
            'value': chat.target_company,
            'placeholder': 'e.g., Google',
        },
        'actions': [
            {'id': 'submit', 'label': 'Next →', 'type': 'button', 'primary': True},
            {'id': 'skip', 'label': 'Skip', 'type': 'button'},
        ],
    }


def _build_experience_level_ui(chat):
    """Build single-select for experience level."""
    options = []
    for level in _EXPERIENCE_LEVELS:
        opt = {'id': level['id'], 'label': level['label']}
        if chat.experience_level == level['id']:
            opt['highlighted'] = True
        options.append(opt)
    return {
        'type': 'single_select',
        'message': 'What\'s your experience level?',
        'options': options,
        'action_id': 'select_level',
    }


def _build_industry_ui(chat):
    """Build button pills for industry selection."""
    buttons = []
    for ind in _INDUSTRIES:
        btn = {'id': ind['id'], 'label': ind['label'], 'type': 'button'}
        if chat.target_industry == ind['id']:
            btn['primary'] = True
        buttons.append(btn)
    return {
        'type': 'buttons',
        'message': 'Which industry?',
        'buttons': buttons,
        'action_id': 'select_industry',
    }


def _build_experience_input_ui(chat):
    """Build mode selection for experience input."""
    experience = chat.resume_data.get('experience', [])
    if experience:
        # Already have experience — show it and ask to add/continue
        return {
            'type': 'buttons',
            'message': f'You have {len(experience)} role(s) from your base. Would you like to review, add more, or continue?',
            'buttons': [
                {'id': 'done_experience', 'label': 'Review experience →', 'type': 'button', 'primary': True},
                {'id': 'select_mode', 'label': '+ Add more roles', 'type': 'button'},
            ],
            'context': {'value': 'structured'},
        }
    return {
        'type': 'buttons',
        'message': 'Now let\'s add your work experience. How would you like to enter it?',
        'buttons': [
            {'id': 'select_mode', 'label': 'Fill in fields', 'type': 'button', 'context': {'value': 'structured'}},
            {'id': 'select_mode', 'label': 'Paste/type freely, AI will structure ✨', 'type': 'button', 'primary': True, 'context': {'value': 'freetext'}},
        ],
    }


def _build_experience_form_ui():
    """Build structured form for adding a single experience entry."""
    return {
        'type': 'form_group',
        'message': 'Tell me about this role:',
        'fields': [
            {'key': 'title', 'type': 'text', 'label': 'Job Title', 'required': True, 'placeholder': 'e.g., Senior Developer'},
            {'key': 'company', 'type': 'text', 'label': 'Company', 'required': True, 'placeholder': 'e.g., Acme Corp'},
            {'key': 'location', 'type': 'text', 'label': 'Location', 'placeholder': 'e.g., Mumbai, India'},
            {'key': 'start_date', 'type': 'text', 'label': 'Start Date', 'required': True, 'placeholder': 'e.g., Jan 2022'},
            {'key': 'end_date', 'type': 'text', 'label': 'End Date', 'placeholder': 'Present'},
            {'key': 'description', 'type': 'textarea', 'label': 'What did you do? (brief is fine, AI can polish later)',
             'placeholder': 'e.g., Led migration of monolith to microservices, reducing deploy time by 60%\nMentored 4 junior developers'},
        ],
        'actions': [
            {'id': 'form_submit', 'label': 'Add Role →', 'type': 'button', 'primary': True},
            {'id': 'back', 'label': '← Back', 'type': 'button'},
        ],
    }


def _build_experience_review_ui(chat):
    """Build card list for reviewing structured experience."""
    experience = chat.resume_data.get('experience', [])
    if not experience:
        return {
            'type': 'buttons',
            'message': 'No work experience added yet. Would you like to add some?',
            'buttons': [
                {'id': 'add', 'label': '+ Add Role', 'type': 'button', 'primary': True},
                {'id': 'continue', 'label': 'Skip experience', 'type': 'button'},
            ],
        }

    cards = [_experience_to_card(exp, i) for i, exp in enumerate(experience)]
    return {
        'type': 'card_list',
        'message': f'Here\'s your work experience ({len(experience)} role{"s" if len(experience) != 1 else ""}). Tap any entry to edit.',
        'cards': cards,
        'actions': [
            {'id': 'add', 'label': '+ Add Role', 'type': 'button'},
            {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
        ],
    }


def _experience_to_card(exp, index):
    """Convert an experience dict to a card spec."""
    bullets = exp.get('bullets', [])
    return {
        'id': f'exp_{index}',
        'card_index': index,
        'editable': True,
        'fields': {
            'title': exp.get('title', ''),
            'company': exp.get('company', ''),
            'location': exp.get('location', ''),
            'start_date': exp.get('start_date', ''),
            'end_date': exp.get('end_date', ''),
            'bullets': bullets,
        },
    }


def _build_education_ui(chat):
    """Build UI for education step."""
    education = chat.resume_data.get('education', [])
    if education:
        cards = []
        for i, edu in enumerate(education):
            cards.append({
                'id': f'edu_{i}',
                'card_index': i,
                'editable': True,
                'fields': {
                    'degree': edu.get('degree', ''),
                    'institution': edu.get('institution', ''),
                    'location': edu.get('location', ''),
                    'year': edu.get('year', ''),
                    'gpa': edu.get('gpa', ''),
                },
            })
        return {
            'type': 'card_list',
            'message': 'Your education. Tap to edit or add more.',
            'cards': cards,
            'actions': [
                {'id': 'add_more', 'label': '+ Add Education', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        }
    return _build_education_form_ui()


def _build_education_form_ui():
    """Build form for adding education."""
    return {
        'type': 'form_group',
        'message': 'Add your education:',
        'fields': [
            {'key': 'degree', 'type': 'text', 'label': 'Degree', 'required': True, 'placeholder': 'e.g., B.Tech Computer Science'},
            {'key': 'institution', 'type': 'text', 'label': 'Institution', 'required': True, 'placeholder': 'e.g., IIT Mumbai'},
            {'key': 'location', 'type': 'text', 'label': 'Location', 'placeholder': 'e.g., Mumbai, India'},
            {'key': 'year', 'type': 'text', 'label': 'Year', 'placeholder': 'e.g., 2019'},
            {'key': 'gpa', 'type': 'text', 'label': 'GPA (optional)', 'placeholder': 'e.g., 8.5/10'},
        ],
        'actions': [
            {'id': 'form_submit', 'label': 'Add Education →', 'type': 'button', 'primary': True},
            {'id': 'skip', 'label': 'Skip', 'type': 'button'},
        ],
    }


def _build_skills_ui(chat):
    """Build multi-select chips for skills."""
    skills = chat.resume_data.get('skills', {})
    existing_technical = skills.get('technical', [])
    existing_tools = skills.get('tools', [])
    existing_soft = skills.get('soft', [])

    # Suggest skills based on industry
    industry = chat.target_industry or 'technology'
    suggested = _INDUSTRY_SKILLS.get(industry, _INDUSTRY_SKILLS['technology'])
    # Don't suggest skills already selected
    all_existing = set(existing_technical + existing_tools + existing_soft)
    suggested_chips = [
        {'id': s, 'label': s, 'selected': False, 'suggested': True}
        for s in suggested if s not in all_existing
    ][:10]  # Limit suggestions

    groups = [
        {
            'key': 'technical',
            'label': 'Technical Skills',
            'chips': [
                {'id': s, 'label': s, 'selected': True} for s in existing_technical
            ] + [c for c in suggested_chips if c not in existing_technical],
            'allow_custom': True,
        },
        {
            'key': 'tools',
            'label': 'Tools & Platforms',
            'chips': [
                {'id': s, 'label': s, 'selected': True} for s in existing_tools
            ],
            'allow_custom': True,
        },
        {
            'key': 'soft',
            'label': 'Soft Skills',
            'chips': [
                {'id': s, 'label': s, 'selected': True} for s in existing_soft
            ] + [
                {'id': s, 'label': s, 'selected': False, 'suggested': True}
                for s in ['Leadership', 'Communication', 'Problem Solving', 'Teamwork', 'Time Management']
                if s not in existing_soft
            ],
            'allow_custom': True,
        },
    ]

    return {
        'type': 'multi_select_chips',
        'message': 'Your skills — toggle to add/remove, or type to add custom ones.',
        'groups': groups,
        'actions': [
            {'id': 'chips', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            {'id': 'skip', 'label': 'Skip', 'type': 'button'},
        ],
    }


def _build_certifications_ui(chat):
    """Build prompt for certifications."""
    certs = chat.resume_data.get('certifications', [])
    if certs:
        cards = []
        for i, cert in enumerate(certs):
            cards.append({
                'id': f'cert_{i}',
                'card_index': i,
                'editable': True,
                'fields': {
                    'name': cert.get('name', ''),
                    'issuer': cert.get('issuer', ''),
                    'year': cert.get('year', ''),
                },
            })
        return {
            'type': 'card_list',
            'message': 'Your certifications:',
            'cards': cards,
            'actions': [
                {'id': 'add_more', 'label': '+ Add Another', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        }
    return {
        'type': 'buttons',
        'message': 'Any certifications you\'d like to add?',
        'buttons': [
            {'id': 'yes', 'label': 'Yes, add certifications', 'type': 'button', 'primary': True},
            {'id': 'no', 'label': 'No, skip', 'type': 'button'},
        ],
    }


def _build_cert_form_ui():
    """Build form for a single certification."""
    return {
        'type': 'form_group',
        'message': 'Add a certification:',
        'fields': [
            {'key': 'name', 'type': 'text', 'label': 'Certification Name', 'required': True, 'placeholder': 'e.g., AWS Solutions Architect'},
            {'key': 'issuer', 'type': 'text', 'label': 'Issuing Organization', 'placeholder': 'e.g., Amazon'},
            {'key': 'year', 'type': 'text', 'label': 'Year Obtained', 'placeholder': 'e.g., 2023'},
        ],
        'actions': [
            {'id': 'form_submit', 'label': 'Add Certification →', 'type': 'button', 'primary': True},
            {'id': 'skip', 'label': 'Skip', 'type': 'button'},
        ],
    }


def _build_projects_ui(chat):
    """Build prompt for projects."""
    projects = chat.resume_data.get('projects', [])
    if projects:
        cards = []
        for i, proj in enumerate(projects):
            cards.append({
                'id': f'proj_{i}',
                'card_index': i,
                'editable': True,
                'fields': {
                    'name': proj.get('name', ''),
                    'description': proj.get('description', ''),
                    'technologies': proj.get('technologies', []),
                    'url': proj.get('url', ''),
                },
            })
        return {
            'type': 'card_list',
            'message': 'Your projects:',
            'cards': cards,
            'actions': [
                {'id': 'add_more', 'label': '+ Add Another', 'type': 'button'},
                {'id': 'continue', 'label': 'Continue ✓', 'type': 'button', 'primary': True},
            ],
        }
    return {
        'type': 'buttons',
        'message': 'Any projects you\'d like to highlight?',
        'buttons': [
            {'id': 'yes', 'label': 'Yes, add projects', 'type': 'button', 'primary': True},
            {'id': 'no', 'label': 'No, skip', 'type': 'button'},
        ],
    }


def _build_project_form_ui():
    """Build form for a single project."""
    return {
        'type': 'form_group',
        'message': 'Add a project:',
        'fields': [
            {'key': 'name', 'type': 'text', 'label': 'Project Name', 'required': True, 'placeholder': 'e.g., ResumeAI'},
            {'key': 'description', 'type': 'textarea', 'label': 'Description', 'placeholder': 'e.g., AI-powered resume analysis platform'},
            {'key': 'technologies', 'type': 'text', 'label': 'Technologies (comma-separated)', 'placeholder': 'e.g., Python, Django, React'},
            {'key': 'url', 'type': 'text', 'label': 'URL (optional)', 'placeholder': 'e.g., https://github.com/...'},
        ],
        'actions': [
            {'id': 'form_submit', 'label': 'Add Project →', 'type': 'button', 'primary': True},
            {'id': 'skip', 'label': 'Skip', 'type': 'button'},
        ],
    }


def _build_review_ui(chat):
    """Build review step with AI polish option."""
    return {
        'type': 'preview',
        'message': 'Almost done! Let me polish your resume with AI — I\'ll generate a professional summary, optimize your bullets for ATS, and add relevant keywords.',
        'resume_data': chat.resume_data,
        'actions': [
            {'id': 'polish', 'label': '✨ Polish with AI & Preview', 'type': 'button', 'primary': True},
            {'id': 'skip_polish', 'label': 'Skip polish, pick template', 'type': 'button'},
            {'id': 'back_to_edit', 'label': '← Go back and edit', 'type': 'button'},
        ],
    }


# ── UI builder registry ──────────────────────────────────────────────────────

_STEP_UI_BUILDERS = {
    ResumeChat.STEP_CONTACT: _build_contact_ui,
    ResumeChat.STEP_TARGET_ROLE: _build_target_role_ui,
    ResumeChat.STEP_EXPERIENCE_INPUT: _build_experience_input_ui,
    ResumeChat.STEP_EXPERIENCE_REVIEW: _build_experience_review_ui,
    ResumeChat.STEP_EDUCATION: _build_education_ui,
    ResumeChat.STEP_SKILLS: _build_skills_ui,
    ResumeChat.STEP_CERTIFICATIONS: _build_certifications_ui,
    ResumeChat.STEP_PROJECTS: _build_projects_ui,
    ResumeChat.STEP_REVIEW: _build_review_ui,
}


# ══════════════════════════════════════════════════════════════════════════════
# LLM Calls — kept to minimum (experience structuring + final polish)
# ══════════════════════════════════════════════════════════════════════════════

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)


def _llm_structure_experience(user, raw_text, target_role=''):
    """
    Call LLM to structure free-text work experience into the resume JSON schema.

    Returns (list_of_experience_dicts, LLMResponse_record).
    """
    from .ai_providers.factory import get_openai_client, llm_retry
    from .ai_providers.base import check_prompt_length
    from .ai_providers.json_repair import repair_json

    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    system_prompt = (
        'You are a professional resume writer. Extract and structure work experience '
        'from the user\'s raw text into clean, professional entries. '
        'Use strong action verbs, quantify achievements where data is provided, '
        'and create impactful bullet points.\n\n'
        'Return ONLY valid JSON — an array of experience objects. No markdown, no explanation.'
    )

    target_context = f'\nTarget role: {target_role}' if target_role else ''
    user_prompt = f"""Structure the following work history into professional resume entries.{target_context}

Raw text:
{raw_text}

Return a JSON array with this schema:
[
  {{
    "title": "Job Title",
    "company": "Company Name",
    "location": "City, Country or empty string",
    "start_date": "Start date as stated",
    "end_date": "End date or Present",
    "bullets": [
      "Achievement-oriented bullet with action verb and quantified impact"
    ]
  }}
]

Rules:
- Each role should have 2-5 bullet points
- Use strong action verbs (Led, Built, Designed, Implemented, etc.)
- Preserve all factual information (dates, names, numbers)
- Quantify impact where the raw text provides numbers
- Return ONLY the JSON array"""

    user_prompt = check_prompt_length(user_prompt)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    req_start = time.time()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4096,
            temperature=0.3,
            timeout=90,
        )

    response = _call()
    elapsed = time.time() - req_start

    raw = response.choices[0].message.content.strip()
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            logger.error('Experience structuring JSON repair failed')
            data = []

    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []

    # Normalize entries
    for entry in data:
        entry.setdefault('title', '')
        entry.setdefault('company', '')
        entry.setdefault('location', '')
        entry.setdefault('start_date', '')
        entry.setdefault('end_date', '')
        entry.setdefault('bullets', [])

    # Save LLM response record
    usage = getattr(response, 'usage', None)
    llm_record = LLMResponse.objects.create(
        user=user,
        prompt_sent=json.dumps(messages),
        raw_response=raw,
        parsed_response=data,
        model_used=model,
        status=LLMResponse.STATUS_DONE,
        duration_seconds=elapsed,
        call_purpose='resume_chat_experience',
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None),
        total_tokens=getattr(usage, 'total_tokens', None),
    )

    logger.info('Experience structured via LLM: %d entries in %.2fs', len(data), elapsed)
    return data, llm_record


def _llm_rewrite_bullets(user, experience_entry, focus_areas, target_role=''):
    """
    Call LLM to rewrite bullets for a single experience entry.

    Returns (list_of_new_bullets, LLMResponse_record).
    """
    from .ai_providers.factory import get_openai_client, llm_retry
    from .ai_providers.json_repair import repair_json

    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    focus_text = ', '.join(focus_areas) if focus_areas else 'general improvement'

    system_prompt = (
        'You are a professional resume writer. Rewrite bullet points to be more impactful. '
        'Return ONLY a JSON array of strings (the new bullets). No markdown, no explanation.'
    )

    user_prompt = f"""Rewrite these resume bullets with a focus on: {focus_text}

Role: {experience_entry.get('title', '')} at {experience_entry.get('company', '')}
Target role: {target_role or 'Not specified'}

Current bullets:
{json.dumps(experience_entry.get('bullets', []), indent=2)}

Rules:
- Use strong action verbs
- Quantify impact where possible
- Focus on: {focus_text}
- Keep 3-5 bullets
- Return ONLY a JSON array of strings"""

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    req_start = time.time()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
            temperature=0.4,
            timeout=60,
        )

    response = _call()
    elapsed = time.time() - req_start

    raw = response.choices[0].message.content.strip()
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            data = experience_entry.get('bullets', [])

    if not isinstance(data, list):
        data = experience_entry.get('bullets', [])

    usage = getattr(response, 'usage', None)
    llm_record = LLMResponse.objects.create(
        user=user,
        prompt_sent=json.dumps(messages),
        raw_response=raw,
        parsed_response=data,
        model_used=model,
        status=LLMResponse.STATUS_DONE,
        duration_seconds=elapsed,
        call_purpose='resume_chat_rewrite',
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None),
        total_tokens=getattr(usage, 'total_tokens', None),
    )

    logger.info('Bullets rewritten via LLM: %d bullets in %.2fs', len(data), elapsed)
    return data, llm_record


def _llm_polish_resume(chat):
    """
    Call LLM to polish the entire resume:
    - Generate professional summary
    - Optimize bullet points for ATS
    - Add relevant keywords for target role

    Returns (polished_resume_data_dict, LLMResponse_record).
    """
    from .ai_providers.factory import get_openai_client, llm_retry
    from .ai_providers.base import check_prompt_length
    from .ai_providers.json_repair import repair_json

    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    system_prompt = (
        'You are a professional resume writer and ATS optimization specialist. '
        'Polish the given resume data by:\n'
        '1. Writing a compelling 2-3 sentence professional summary\n'
        '2. Optimizing all bullet points with strong action verbs and quantified impact\n'
        '3. Adding relevant keywords naturally for ATS compatibility\n'
        '4. Ensuring consistent formatting and professional language\n\n'
        'Critical rules:\n'
        '- Do NOT fabricate experience, degrees, or skills not present in the input\n'
        '- Only enhance and rephrase what exists\n'
        '- Preserve all factual information (dates, company names, numbers)\n'
        '- Return ONLY valid JSON matching the input schema. No markdown, no explanation.'
    )

    target_context = ''
    if chat.target_role:
        target_context += f'\nTarget Role: {chat.target_role}'
    if chat.target_company:
        target_context += f'\nTarget Company: {chat.target_company}'
    if chat.target_industry:
        target_context += f'\nIndustry: {chat.target_industry}'
    if chat.experience_level:
        target_context += f'\nExperience Level: {chat.experience_level}'

    user_prompt = f"""Polish and optimize this resume data for ATS compatibility.{target_context}

Current resume data:
{json.dumps(chat.resume_data, indent=2)}

Return the COMPLETE polished resume as JSON with the same schema:
{{
  "contact": {{ "name", "email", "phone", "location", "linkedin", "portfolio" }},
  "summary": "2-3 sentence professional summary tailored to target role",
  "experience": [ {{ "title", "company", "location", "start_date", "end_date", "bullets": [...] }} ],
  "education": [ {{ "degree", "institution", "location", "year", "gpa" }} ],
  "skills": {{ "technical": [...], "tools": [...], "soft": [...] }},
  "certifications": [ {{ "name", "issuer", "year" }} ],
  "projects": [ {{ "name", "description", "technologies": [...], "url" }} ]
}}

Rules:
- Write a NEW professional summary (the "summary" field) tailored to the target role
- Enhance bullet points with stronger action verbs and quantified impact
- Do NOT change contact info, dates, company names, or degree names
- Keep skills lists but you may reorganize them
- Return ONLY the JSON object"""

    user_prompt = check_prompt_length(user_prompt)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    req_start = time.time()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8192,
            temperature=0.3,
            timeout=120,
        )

    response = _call()
    elapsed = time.time() - req_start

    raw = response.choices[0].message.content.strip()
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            logger.error('Resume polish JSON repair failed')
            # Return original data on failure
            data = copy.deepcopy(chat.resume_data)

    # Ensure all keys exist
    for key in ('contact', 'summary', 'experience', 'education', 'skills', 'certifications', 'projects'):
        if key not in data:
            data[key] = chat.resume_data.get(key, _empty_resume_data()[key])

    usage = getattr(response, 'usage', None)
    llm_record = LLMResponse.objects.create(
        user=chat.user,
        prompt_sent=json.dumps(messages),
        raw_response=raw,
        parsed_response=data,
        model_used=model,
        status=LLMResponse.STATUS_DONE,
        duration_seconds=elapsed,
        call_purpose='resume_chat_polish',
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None),
        total_tokens=getattr(usage, 'total_tokens', None),
    )

    logger.info('Resume polished via LLM in %.2fs', elapsed)
    return data, llm_record


# ══════════════════════════════════════════════════════════════════════════════
# Template Picker Helper
# ══════════════════════════════════════════════════════════════════════════════

def _build_template_picker_data():
    """Build template picker data from DB."""
    from ..models import ResumeTemplate
    templates = ResumeTemplate.objects.filter(is_active=True).order_by('sort_order', 'name')
    return {
        'templates': [
            {
                'slug': t.slug,
                'name': t.name,
                'description': t.description,
                'category': t.category,
                'is_premium': t.is_premium,
                'preview_image_url': t.preview_image.url if t.preview_image else None,
            }
            for t in templates
        ],
        'formats': ['pdf', 'docx'],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Finalize — generate PDF/DOCX from resume_data
# ══════════════════════════════════════════════════════════════════════════════

def finalize_resume(chat, template_slug, fmt):
    """
    Create a GeneratedResume from the chat's resume_data and dispatch
    the rendering Celery task.

    This is called from the view after credit deduction.
    Returns the GeneratedResume instance.
    """
    # Validate resume_data has minimum content
    resume_data = chat.resume_data or {}
    contact = resume_data.get('contact', {})
    if not contact.get('name', '').strip():
        raise ValueError('Resume must have at least a name in contact info.')

    # Create a GeneratedResume record (analysis=None for builder-created resumes)
    gen = GeneratedResume.objects.create(
        user=chat.user,
        analysis=None,
        template=template_slug,
        format=fmt,
        status=GeneratedResume.STATUS_PENDING,
        resume_content=resume_data,
        credits_deducted=True,
    )

    chat.generated_resume = gen
    chat.status = ResumeChat.STATUS_COMPLETED
    chat.current_step = ResumeChat.STEP_DONE
    chat.credits_deducted = True
    chat.save(update_fields=[
        'generated_resume', 'status', 'current_step',
        'credits_deducted', 'updated_at',
    ])

    return gen


def get_user_resumes_for_selection(user):
    """
    Get a list of user's resumes suitable for the base resume selection step.
    Returns both uploaded resumes and generated resumes.
    """
    resumes = []

    # Uploaded resumes
    for r in Resume.objects.filter(user=user).order_by('-uploaded_at')[:10]:
        resumes.append({
            'id': str(r.id),
            'type': 'uploaded',
            'label': r.original_filename,
            'date': r.uploaded_at.strftime('%b %d, %Y'),
        })

    return resumes


# ══════════════════════════════════════════════════════════════════════════════
# Text-Based Chat Mode — pure LLM conversation
# ══════════════════════════════════════════════════════════════════════════════

# Sections the LLM should collect
_RESUME_SECTIONS = ['contact', 'experience', 'education', 'skills', 'certifications', 'projects']

_TEXT_CHAT_SYSTEM_PROMPT = """\
You are a friendly, professional resume builder assistant. You help users \
create their resume through natural conversation.

CURRENT RESUME DATA:
{resume_data}

SECTIONS TO COLLECT:
1. contact — name, email, phone, location, linkedin, portfolio
2. experience — list of jobs: title, company, location, start_date, end_date, bullets (achievements)
3. education — list of degrees: degree, institution, location, year, gpa
4. skills — technical (list), tools (list), soft (list)
5. certifications — list: name, issuer, year  (optional)
6. projects — list: name, description, technologies (list), url  (optional)

SECTIONS WITH DATA: {filled_sections}
SECTIONS STILL EMPTY: {empty_sections}

RULES:
- Be concise. 1-3 sentences per response.
- Ask about ONE section at a time, focusing on the next empty section.
- If the user gives info about multiple sections at once, extract ALL of it.
- For work experience bullets, use strong action verbs and preserve numbers/metrics.
- Do NOT invent data. Only include what the user actually said.
- When all key sections (contact + experience) have data, mention they can \
type "done" or keep adding sections. Don't push to finalize too early.
- If the user says "done", "finish", "finalize", or similar, set ready_to_finalize: true.
- If the user asks to change/edit something, update only the mentioned fields.
- Certifications and projects are optional — don't insist on them.

FORMATTING (for the "message" field):
- Use **Markdown** for rich formatting in your conversational text.
- Use **bold** for emphasis and section labels.
- Use bullet lists (`- `) when listing items or skills.
- Use `inline code` for technical terms like tool names.
- Keep it conversational — don't over-format. A natural chat feel is key.
- Example: "Great! I've added your role as **Senior Developer** at **Acme Corp**."

YOU MUST RESPOND WITH VALID JSON ONLY (no markdown fences, no extra text):
{{
  "message": "Your conversational response (use Markdown formatting)",
  "data_updates": {{
    // ONLY include sections with NEW or CHANGED data.
    // Use the exact same schema as CURRENT RESUME DATA above.
    // Omit sections with no changes.
  }},
  "sections_with_data": ["contact", "experience"],
  "current_focus": "experience",
  "ready_to_finalize": false
}}"""


def _get_filled_sections(resume_data: dict) -> list[str]:
    """Return list of section names that have meaningful data."""
    filled = []
    contact = resume_data.get('contact', {})
    if contact.get('name') or contact.get('email'):
        filled.append('contact')
    if resume_data.get('experience'):
        filled.append('experience')
    if resume_data.get('education'):
        filled.append('education')
    skills = resume_data.get('skills', {})
    if any(skills.get(k) for k in ('technical', 'tools', 'soft')):
        filled.append('skills')
    if resume_data.get('certifications'):
        filled.append('certifications')
    if resume_data.get('projects'):
        filled.append('projects')
    return filled


def _merge_data_updates(resume_data: dict, updates: dict) -> dict:
    """
    Merge LLM-provided data_updates into resume_data.

    - For dict sections (contact, skills): shallow merge keys.
    - For list sections (experience, education, etc.): replace if update is
      non-empty, otherwise keep existing. This avoids duplicating entries
      when the LLM echoes back the same data.
    """
    result = copy.deepcopy(resume_data)

    for section, value in updates.items():
        if section not in result:
            result[section] = value
            continue

        if isinstance(value, dict) and isinstance(result[section], dict):
            # Merge dict-type sections (contact, skills)
            for k, v in value.items():
                if v not in (None, '', []):
                    result[section][k] = v
        elif isinstance(value, list) and value:
            # For list sections, LLM returns the full list — replace
            result[section] = value
        elif isinstance(value, str) and value:
            result[section] = value

    return result


def start_text_session(user, source: str, base_resume_id: str = None) -> ResumeChat:
    """
    Start a pure text chat session for resume building.

    Path 1 (scratch):   Empty data. AI asks everything from zero.
    Path 2 (previous):  Load from selected resume's analysis. Summarize what was found.
    Path 3 (profile):   Load from UserProfile. Show what was pulled, ask to confirm.

    All paths converge into the same text conversation after the welcome message.
    """
    chat = ResumeChat.objects.create(
        user=user,
        source=source,
        mode=ResumeChat.MODE_TEXT,
        current_step=ResumeChat.STEP_CONTACT,
    )

    resume_data = _empty_resume_data()

    if source == ResumeChat.SOURCE_PROFILE:
        resume_data = _prefill_from_profile(user, resume_data)
    elif source == ResumeChat.SOURCE_PREVIOUS:
        resume_data = _prefill_from_resume(user, base_resume_id, resume_data)
        if base_resume_id:
            try:
                chat.base_resume = Resume.objects.get(id=base_resume_id, user=user)
                chat.save(update_fields=['base_resume'])
            except Resume.DoesNotExist:
                pass

    chat.resume_data = resume_data
    chat.save(update_fields=['resume_data'])

    # ── Build contextual welcome message ────────────────────────────────
    welcome = _build_welcome_message(source, resume_data, user)

    ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_ASSISTANT,
        content=welcome,
        step='contact',
    )

    return chat


def _build_welcome_message(source: str, resume_data: dict, user) -> str:
    """Build a contextual welcome message based on source and pre-filled data."""

    # ── Path 1: From scratch ────────────────────────────────────────────
    if source == ResumeChat.SOURCE_SCRATCH:
        return (
            "Hi! I'll help you build your resume **from scratch** through a quick conversation.\n\n"
            "Let's start with the basics — what's your **full name**, **email**, and **phone number**?"
        )

    # ── Path 3: From profile ────────────────────────────────────────────
    if source == ResumeChat.SOURCE_PROFILE:
        contact = resume_data.get('contact', {})
        name = contact.get('name', '').strip()
        parts = []
        if name:
            parts.append(f"Name: {name}")
        if contact.get('email'):
            parts.append(f"Email: {contact['email']}")
        if contact.get('phone'):
            parts.append(f"Phone: {contact['phone']}")
        if contact.get('linkedin'):
            parts.append(f"LinkedIn: {contact['linkedin']}")

        skills = resume_data.get('skills', {})
        skill_list = skills.get('technical', [])

        greeting = f"Hi{' ' + name.split()[0] if name else ''}!"
        lines = [f"{greeting} I pulled this from your profile:\n"]
        if parts:
            lines.append('\n'.join(f"- **{p.split(':')[0].strip()}:** {':'.join(p.split(':')[1:]).strip()}" if ':' in p else f"- {p}" for p in parts))
        if skill_list:
            lines.append(f"\n**Skills:** {', '.join(f'`{s}`' for s in skill_list[:10])}")
        lines.append(
            "\n\nDoes this look correct? Feel free to update anything, "
            "or just say **\"looks good\"** and we'll move on to your work experience."
        )
        return '\n'.join(lines)

    # ── Path 2: From existing resume ────────────────────────────────────
    contact = resume_data.get('contact', {})
    name = contact.get('name', '').strip()
    experience = resume_data.get('experience', [])
    education = resume_data.get('education', [])
    skills = resume_data.get('skills', {})
    filled = _get_filled_sections(resume_data)

    greeting = f"Hi{' ' + name.split()[0] if name else ''}!"
    lines = [f"{greeting} I've loaded data from your resume. Here's what I found:\n"]

    if contact.get('name') or contact.get('email'):
        contact_parts = []
        if contact.get('name'):
            contact_parts.append(contact['name'])
        if contact.get('email'):
            contact_parts.append(contact['email'])
        lines.append(f"- **Contact:** {', '.join(contact_parts)}")

    if experience:
        exp_summary = []
        for exp in experience[:3]:
            title = exp.get('title', '')
            company = exp.get('company', '')
            if title and company:
                exp_summary.append(f"{title} @ {company}")
            elif title:
                exp_summary.append(title)
        lines.append(f"- **Experience:** {len(experience)} role(s) — {'; '.join(exp_summary)}")

    if education:
        edu_summary = []
        for edu in education[:2]:
            degree = edu.get('degree', '')
            institution = edu.get('institution', '')
            if degree and institution:
                edu_summary.append(f"{degree}, {institution}")
            elif degree:
                edu_summary.append(degree)
        lines.append(f"- **Education:** {'; '.join(edu_summary)}")

    all_skills = skills.get('technical', []) + skills.get('tools', [])
    if all_skills:
        lines.append(f"- **Skills:** {', '.join(f'`{s}`' for s in all_skills[:8])}")

    empty = [s for s in _RESUME_SECTIONS if s not in filled]
    if empty:
        lines.append(f"\n> **Still missing:** {', '.join(empty)}")

    lines.append(
        "\nWant to update anything, add missing sections, "
        "or tell me what role you're targeting so I can tailor the resume?"
    )
    return '\n'.join(lines)

    ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_ASSISTANT,
        content=welcome,
        step='contact',
    )

    return chat


def process_text_message(chat: ResumeChat, user_text: str) -> dict:
    """
    Process a free-text user message in text chat mode.

    1. Saves the user message
    2. Builds conversation context (last 20 messages + resume_data)
    3. Calls LLM to get response + data updates
    4. Merges extracted data into resume_data
    5. Returns response dict for the view

    Returns:
        {
            'user_message': ResumeChatMessage,
            'assistant_message': ResumeChatMessage,
            'resume_data': dict,
            'progress': {
                'sections_with_data': list,
                'total_sections': int,
                'ready_to_finalize': bool,
                'current_focus': str,
            },
        }
    """
    from .ai_providers.factory import get_openai_client, llm_retry
    from .ai_providers.json_repair import repair_json

    # 1. Save user message
    user_msg = ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_USER,
        content=user_text,
        step=chat.current_step,
    )

    # 2. Build conversation for LLM
    resume_data = chat.resume_data or _empty_resume_data()
    filled = _get_filled_sections(resume_data)
    empty = [s for s in _RESUME_SECTIONS if s not in filled]

    system_prompt = _TEXT_CHAT_SYSTEM_PROMPT.format(
        resume_data=json.dumps(resume_data, indent=2),
        filled_sections=', '.join(filled) or 'none',
        empty_sections=', '.join(empty) or 'none',
    )

    # Get last N messages for conversation context
    recent_messages = list(
        chat.messages.filter(
            role__in=[ResumeChatMessage.ROLE_USER, ResumeChatMessage.ROLE_ASSISTANT]
        ).order_by('-created_at')[:20]
    )
    recent_messages.reverse()

    llm_messages = [{'role': 'system', 'content': system_prompt}]
    for msg in recent_messages:
        if msg.role == ResumeChatMessage.ROLE_ASSISTANT:
            # For assistant messages, we only send the text (not raw JSON)
            llm_messages.append({'role': 'assistant', 'content': msg.content})
        else:
            llm_messages.append({'role': 'user', 'content': msg.content})

    # 3. Call LLM
    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    req_start = time.time()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=llm_messages,
            max_tokens=2048,
            temperature=0.4,
            timeout=60,
        )

    try:
        response = _call()
    except Exception as exc:
        logger.exception('Text chat LLM call failed: chat=%s', chat.id)
        # Return a graceful fallback
        fallback_msg = ResumeChatMessage.objects.create(
            chat=chat,
            role=ResumeChatMessage.ROLE_ASSISTANT,
            content="Sorry, I had trouble processing that. Could you try again?",
            step=chat.current_step,
        )
        return {
            'user_message': user_msg,
            'assistant_message': fallback_msg,
            'resume_data': resume_data,
            'progress': {
                'sections_with_data': filled,
                'total_sections': len(_RESUME_SECTIONS),
                'ready_to_finalize': False,
                'current_focus': empty[0] if empty else 'review',
            },
        }

    elapsed = time.time() - req_start

    # 4. Parse LLM response
    raw = response.choices[0].message.content.strip()
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            logger.error('Text chat JSON parse failed: chat=%s raw=%s', chat.id, raw[:200])
            parsed = {'message': raw, 'data_updates': {}, 'sections_with_data': filled,
                       'current_focus': empty[0] if empty else 'review', 'ready_to_finalize': False}

    response_text = parsed.get('message', '')
    data_updates = parsed.get('data_updates', {})
    sections_with_data = parsed.get('sections_with_data', filled)
    current_focus = parsed.get('current_focus', empty[0] if empty else 'review')
    ready_to_finalize = parsed.get('ready_to_finalize', False)

    # 5. Merge data updates into resume_data
    if data_updates:
        resume_data = _merge_data_updates(resume_data, data_updates)
        chat.resume_data = resume_data

    # Update target_role / target_company if the LLM extracted them
    if data_updates.get('target_role'):
        chat.target_role = data_updates['target_role']
    if data_updates.get('target_company'):
        chat.target_company = data_updates['target_company']

    # Track current step based on focus
    step_map = {
        'contact': ResumeChat.STEP_CONTACT,
        'experience': ResumeChat.STEP_EXPERIENCE_INPUT,
        'education': ResumeChat.STEP_EDUCATION,
        'skills': ResumeChat.STEP_SKILLS,
        'certifications': ResumeChat.STEP_CERTIFICATIONS,
        'projects': ResumeChat.STEP_PROJECTS,
        'review': ResumeChat.STEP_REVIEW,
    }
    if current_focus in step_map:
        chat.current_step = step_map[current_focus]

    chat.save(update_fields=['resume_data', 'current_step', 'target_role', 'target_company', 'updated_at'])

    # Recompute filled sections after merge
    filled = _get_filled_sections(resume_data)

    # Save LLM record for cost tracking
    usage = getattr(response, 'usage', None)
    llm_record = LLMResponse.objects.create(
        user=chat.user,
        prompt_sent=json.dumps(llm_messages[:2]),  # system + first user msg only (save space)
        raw_response=raw,
        parsed_response=parsed,
        model_used=model,
        status=LLMResponse.STATUS_DONE,
        duration_seconds=elapsed,
        call_purpose='resume_chat_text',
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None),
        total_tokens=getattr(usage, 'total_tokens', None),
    )

    # 6. Save assistant message
    assistant_msg = ResumeChatMessage.objects.create(
        chat=chat,
        role=ResumeChatMessage.ROLE_ASSISTANT,
        content=response_text,
        extracted_data=data_updates if data_updates else None,
        step=chat.current_step,
        llm_response=llm_record,
    )

    logger.info(
        'Text chat message processed: chat=%s focus=%s sections=%s elapsed=%.2fs',
        chat.id, current_focus, ','.join(filled), elapsed,
    )

    return {
        'user_message': user_msg,
        'assistant_message': assistant_msg,
        'resume_data': resume_data,
        'progress': {
            'sections_with_data': filled,
            'total_sections': len(_RESUME_SECTIONS),
            'ready_to_finalize': ready_to_finalize,
            'current_focus': current_focus,
        },
    }
