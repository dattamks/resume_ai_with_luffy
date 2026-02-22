import json
import logging

import anthropic
from django.conf import settings

from .base import AIProvider, validate_ai_response

logger = logging.getLogger('analyzer')


class ClaudeProvider(AIProvider):
    """Resume analyzer backed by Anthropic Claude."""

    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-6'):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def analyze(self, resume_text: str, job_description: str) -> dict:
        import time
        prompt = self._build_prompt(resume_text, job_description)
        max_tokens = getattr(settings, 'AI_MAX_TOKENS', 4096)

        messages = [{'role': 'user', 'content': prompt}]

        req_start = time.time()
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
        )
        elapsed = time.time() - req_start

        raw = message.content[0].text.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error('Claude returned non-JSON response: %s', raw)
            raise ValueError(f'Claude returned non-JSON response: {exc}') from exc

        try:
            validate_ai_response(data)
        except ValueError as exc:
            logger.error('Claude response failed schema validation: %s | raw=%s', exc, raw)
            raise

        return {
            'parsed': data,
            'raw': raw,
            'prompt': json.dumps(messages),
            'model': self.model,
            'duration': elapsed,
        }
