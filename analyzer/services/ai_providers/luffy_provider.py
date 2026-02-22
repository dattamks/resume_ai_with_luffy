import json
import logging

import requests
from django.conf import settings

from .base import AIProvider, validate_ai_response
from .json_repair import repair_json

logger = logging.getLogger('analyzer')


class LuffyProvider(AIProvider):
    """Resume analyzer backed by a self-deployed LLM (Ollama-compatible API)."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str = 'luffy',
        timeout: int = 300,
        stream: bool = False,
        think: bool = False,
        system_role: str = '',
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.stream = stream
        self.think = think
        # Pipe-delimited string → list of system role messages
        self.system_roles = [
            r.strip() for r in system_role.split('|') if r.strip()
        ] if system_role else []

    def analyze(self, resume_text: str, job_description: str) -> dict:
        """
        Run analysis. Returns a dict with keys:
          - 'parsed': validated analysis JSON (the schema result)
          - 'raw': raw LLM text output as-is
          - 'prompt': the full prompt/messages sent
          - 'model': model name used
          - 'duration': seconds the API call took
        """
        import time
        print(f'[DEBUG]   LuffyProvider: building prompt...')
        prompt = self._build_prompt(resume_text, job_description)
        print(f'[DEBUG]   LuffyProvider: prompt length: {len(prompt)} chars')
        print(f'[DEBUG]   LuffyProvider: stream={self.stream}, think={self.think}')
        print(f'[DEBUG]   LuffyProvider: system_roles ({len(self.system_roles)}): {[r[:60]+"..." if len(r)>60 else r for r in self.system_roles]}')

        # Build messages array: system role(s) + user prompt
        messages = []
        for role_text in self.system_roles:
            messages.append({'role': 'system', 'content': role_text})
        messages.append({'role': 'user', 'content': prompt})

        # Use the chat endpoint with messages array
        chat_url = self.api_url.replace('/api/generate', '/api/chat')
        print(f'[DEBUG]   LuffyProvider: sending request to {chat_url} (model={self.model}, timeout={self.timeout}s)...')

        req_start = time.time()
        try:
            response = requests.post(
                chat_url,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': self.api_key,
                },
                json={
                    'model': self.model,
                    'messages': messages,
                    'stream': self.stream,
                    'think': self.think,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            elapsed = time.time() - req_start
            print(f'[DEBUG]   LuffyProvider: ❌ API request failed after {elapsed:.2f}s: {exc}')
            logger.error('Luffy API request failed: %s', exc)
            raise ValueError(f'Luffy API request failed: {exc}') from exc

        elapsed = time.time() - req_start
        print(f'[DEBUG]   LuffyProvider: ✅ got response (HTTP {response.status_code}, {len(response.text)} bytes, {elapsed:.2f}s)')

        try:
            api_result = response.json()
        except (ValueError, KeyError) as exc:
            print(f'[DEBUG]   LuffyProvider: ❌ invalid JSON wrapper')
            logger.error('Luffy returned invalid JSON wrapper: %s', response.text[:500])
            raise ValueError(f'Luffy returned invalid response: {exc}') from exc

        # Chat API returns {message: {role, content}} instead of {response: ...}
        raw = ''
        if 'message' in api_result and isinstance(api_result['message'], dict):
            raw = api_result['message'].get('content', '')
        elif 'response' in api_result:
            raw = api_result['response']

        if not raw:
            print(f'[DEBUG]   LuffyProvider: ❌ empty response field')
            logger.error('Luffy returned empty response: %s', api_result)
            raise ValueError('Luffy returned an empty response.')

        print(f'[DEBUG]   LuffyProvider: raw response length: {len(raw)} chars')
        print(f'[DEBUG]   LuffyProvider: raw response preview: {raw[:200]}...')

        # Strip markdown code fences if the model wraps the JSON in ```json ... ```
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            print(f'[DEBUG]   LuffyProvider: stripping markdown code fences')
            first_newline = cleaned.index('\n')
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        print(f'[DEBUG]   LuffyProvider: parsing JSON ({len(cleaned)} chars)...')
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            print(f'[DEBUG]   LuffyProvider: ⚠️ JSON parse failed: {exc}')
            print(f'[DEBUG]   LuffyProvider: attempting JSON repair...')
            try:
                repaired = repair_json(cleaned)
                data = json.loads(repaired)
                print(f'[DEBUG]   LuffyProvider: ✅ JSON repair succeeded')
            except json.JSONDecodeError as exc2:
                print(f'[DEBUG]   LuffyProvider: ❌ JSON repair also failed: {exc2}')
                print(f'[DEBUG]   LuffyProvider: cleaned content: {cleaned[:300]}...')
                logger.error('Luffy returned non-JSON response: %s', raw[:500])
                raise ValueError(f'Luffy returned non-JSON response: {exc}') from exc2

        print(f'[DEBUG]   LuffyProvider: ✅ JSON parsed — keys: {list(data.keys())}')

        print(f'[DEBUG]   LuffyProvider: validating schema...')
        try:
            validate_ai_response(data)
        except ValueError as exc:
            print(f'[DEBUG]   LuffyProvider: ❌ schema validation failed: {exc}')
            logger.error('Luffy response failed schema validation: %s | raw=%s', exc, raw[:500])
            raise

        print(f'[DEBUG]   LuffyProvider: ✅ schema validation passed')
        return {
            'parsed': data,
            'raw': raw,
            'prompt': json.dumps(messages),
            'model': self.model,
            'duration': elapsed,
        }
