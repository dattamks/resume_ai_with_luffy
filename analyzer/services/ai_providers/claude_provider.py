import json

import anthropic

from .base import AIProvider


class ClaudeProvider(AIProvider):
    """Resume analyzer backed by Anthropic Claude."""

    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-6'):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def analyze(self, resume_text: str, job_description: str) -> dict:
        prompt = self._build_prompt(resume_text, job_description)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{'role': 'user', 'content': prompt}],
        )

        raw = message.content[0].text.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Claude returned non-JSON response: {raw[:200]}') from exc
