import json
import logging

from openai import OpenAI
from django.conf import settings

from .base import AIProvider, validate_ai_response

logger = logging.getLogger('analyzer')


class OpenAIProvider(AIProvider):
    """Resume analyzer backed by OpenAI."""

    def __init__(self, api_key: str, model: str = 'gpt-4o'):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def analyze(self, resume_text: str, job_description: str) -> dict:
        prompt = self._build_prompt(resume_text, job_description)
        max_tokens = getattr(settings, 'AI_MAX_TOKENS', 4096)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens,
            response_format={'type': 'json_object'},
        )

        raw = response.choices[0].message.content.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error('OpenAI returned non-JSON response: %s', raw)
            raise ValueError(f'OpenAI returned non-JSON response: {exc}') from exc

        try:
            validate_ai_response(data)
        except ValueError as exc:
            logger.error('OpenAI response failed schema validation: %s | raw=%s', exc, raw)
            raise

        return data
