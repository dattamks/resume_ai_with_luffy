import json
import logging
import re
import time

from django.conf import settings

from .base import AIProvider, SYSTEM_PROMPT, validate_ai_response, coerce_ai_response, LLMValidationError
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
        from .factory import _get_openai_client
        self.client = _get_openai_client(api_key, base_url)
        self.model = model

    def _call_llm(self, messages: list, max_tokens: int, temperature: float = 0.3, timeout: int = 120):
        """Call the LLM API with automatic retry on transient failures."""
        from .factory import llm_retry
        @llm_retry
        def _do_call():
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        return _do_call()

    # Maximum schema-validation retries (same prompt, new LLM call)
    _MAX_VALIDATION_RETRIES = 1

    def analyze(self, resume_text: str, job_description: str) -> dict:
        prompt = self._build_prompt(resume_text, job_description)
        max_tokens = getattr(settings, 'AI_MAX_TOKENS', 8192)

        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ]

        last_exc: Exception | None = None
        total_usage: dict = {}
        total_elapsed: float = 0.0
        last_raw: str = ''

        for attempt in range(1 + self._MAX_VALIDATION_RETRIES):
            if attempt > 0:
                logger.warning(
                    'OpenRouter: validation retry %d/%d — re-calling LLM',
                    attempt, self._MAX_VALIDATION_RETRIES,
                )

            logger.info('OpenRouter: sending request — model=%s (attempt %d)', self.model, attempt + 1)
            req_start = time.time()

            response = self._call_llm(messages, max_tokens)

            elapsed = time.time() - req_start
            total_elapsed += elapsed
            logger.info('OpenRouter: response received in %.2fs', elapsed)

            # ── P4: Detect truncated output ──
            finish_reason = None
            if response.choices:
                finish_reason = getattr(response.choices[0], 'finish_reason', None)
            if finish_reason == 'length':
                logger.warning(
                    'OpenRouter: output truncated (finish_reason=length, max_tokens=%d). '
                    'Will attempt JSON repair.',
                    max_tokens,
                )

            # Extract token usage from API response
            usage = {}
            if hasattr(response, 'usage') and response.usage:
                usage = {
                    'prompt_tokens': getattr(response.usage, 'prompt_tokens', None),
                    'completion_tokens': getattr(response.usage, 'completion_tokens', None),
                    'total_tokens': getattr(response.usage, 'total_tokens', None),
                }
                logger.info(
                    'OpenRouter token usage: prompt=%s completion=%s total=%s',
                    usage.get('prompt_tokens'), usage.get('completion_tokens'), usage.get('total_tokens'),
                )
                # Accumulate usage across retries
                for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                    prev = total_usage.get(k) or 0
                    cur = usage.get(k) or 0
                    total_usage[k] = prev + cur

            raw = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None
            if not raw:
                raise LLMValidationError(
                    'OpenRouter returned an empty response (content moderation refusal or empty choices).',
                    raw_response='',
                )
            last_raw = raw

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
                    logger.error('OpenRouter JSON repair failed (raw length=%d)', len(raw))
                    last_exc = LLMValidationError(
                        'OpenRouter returned non-JSON response and repair failed.',
                        raw_response=last_raw,
                    )
                    continue  # retry

            # ── P0: Coerce before validating ──
            coerce_fixes = coerce_ai_response(data)

            try:
                validate_ai_response(data)
            except ValueError as exc:
                logger.error(
                    'OpenRouter response failed schema validation (attempt %d): %s',
                    attempt + 1, exc,
                )
                last_exc = LLMValidationError(str(exc), raw_response=last_raw)
                continue  # retry

            # Success — return result
            return {
                'parsed': data,
                'raw': last_raw,
                'prompt': json.dumps(messages),
                'model': self.model,
                'duration': total_elapsed,
                'usage': total_usage if total_usage else usage,
                'coerce_fixes': coerce_fixes,
            }

        # All attempts exhausted — raise last error with raw response attached
        raise last_exc
