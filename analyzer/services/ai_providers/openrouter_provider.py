import json
import logging
import re
import time

from openai import OpenAI
from django.conf import settings

from .base import AIProvider, validate_ai_response
from .json_repair import repair_json

logger = logging.getLogger('analyzer')

# Strip markdown code fences that LLMs often wrap JSON in
_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)


class OpenRouterProvider(AIProvider):
    """
    Resume analyzer backed by OpenRouter (OpenAI-compatible API).
    Streaming and thinking are disabled — simple request/response.
    """

    def __init__(self, api_key: str, model: str, base_url: str = 'https://openrouter.ai/api/v1'):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

    def analyze(self, resume_text: str, job_description: str) -> dict:
        prompt = self._build_prompt(resume_text, job_description)
        max_tokens = getattr(settings, 'AI_MAX_TOKENS', 4096)

        messages = [
            {
                'role': 'system',
                'content': (
                    'You are an expert resume reviewer and ATS optimization specialist. '
                    'Return ONLY valid JSON — no markdown, no explanation, no extra text.'
                ),
            },
            {'role': 'user', 'content': prompt},
        ]

        logger.info('OpenRouter: sending request — model=%s', self.model)
        req_start = time.time()

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
            timeout=120,  # 2 min hard timeout to prevent hung workers
        )

        elapsed = time.time() - req_start
        logger.info('OpenRouter: response received in %.2fs', elapsed)

        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences (```json ... ```) that LLMs often wrap around JSON
        fence_match = _MD_FENCE_RE.match(raw)
        if fence_match:
            raw = fence_match.group(1).strip()

        # Try to parse JSON — repair if needed
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning('OpenRouter returned non-JSON, attempting repair...')
            repaired_str = repair_json(raw)
            try:
                data = json.loads(repaired_str)
            except json.JSONDecodeError:
                logger.error('OpenRouter JSON repair failed: %s', raw[:500])
                raise ValueError('OpenRouter returned non-JSON response and repair failed.')

        try:
            validate_ai_response(data)
        except ValueError as exc:
            logger.error('OpenRouter response failed schema validation: %s | raw=%s', exc, raw[:500])
            raise

        return {
            'parsed': data,
            'raw': raw,
            'prompt': json.dumps(messages),
            'model': self.model,
            'duration': elapsed,
        }
