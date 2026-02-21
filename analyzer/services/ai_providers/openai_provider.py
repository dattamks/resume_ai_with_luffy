import json

from openai import OpenAI

from .base import AIProvider


class OpenAIProvider(AIProvider):
    """Resume analyzer backed by OpenAI."""

    def __init__(self, api_key: str, model: str = 'gpt-4o'):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def analyze(self, resume_text: str, job_description: str) -> dict:
        prompt = self._build_prompt(resume_text, job_description)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=4096,
            response_format={'type': 'json_object'},
        )

        raw = response.choices[0].message.content.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'OpenAI returned non-JSON response: {raw[:200]}') from exc
