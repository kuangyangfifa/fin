"""AI provider abstraction layer for Claude, Qwen and DeepSeek (OpenAI-compatible)."""

import json
from flask import current_app


class ClaudeProvider:
    """Provider for Anthropic Claude API."""

    def __init__(self, api_key):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)

    def chat(self, messages, max_tokens=1024, system=None):
        """Send a chat request to Claude API.

        Args:
            messages: List of dicts with 'role' and 'content'.
            max_tokens: Maximum tokens in response.
            system: Optional system prompt.

        Returns:
            The text content of the first block, or None on error.
        """
        try:
            # Claude expects 'user' and 'assistant' roles; map accordingly
            formatted = []
            for msg in messages:
                role = msg['role']
                if role == 'system':
                    system = msg['content']
                    continue
                formatted.append({'role': role, 'content': msg['content']})

            response = self.client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=max_tokens,
                system=system,
                messages=formatted,
            )
            return response.content[0].text
        except Exception:
            current_app.logger.exception('Claude API call failed')
            return None

    def parse_json_response(self, response_text):
        """Try to extract JSON from the response text."""
        if not response_text:
            return None
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to find a JSON block
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1:
                try:
                    return json.loads(response_text[start:end + 1])
                except json.JSONDecodeError:
                    return None
            return None


class QwenProvider:
    """Provider for Alibaba Qwen API (OpenAI-compatible)."""

    def __init__(self, api_key, base_url=None):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        )

    def chat(self, messages, max_tokens=1024, system=None):
        """Send a chat request to Qwen API.

        Args:
            messages: List of dicts with 'role' and 'content'.
            max_tokens: Maximum tokens in response.
            system: Optional system prompt (inserted as first message).

        Returns:
            The text content of the response, or None on error.
        """
        try:
            formatted = []
            if system:
                formatted.append({'role': 'system', 'content': system})
            for msg in messages:
                formatted.append({'role': msg['role'], 'content': msg['content']})

            response = self.client.chat.completions.create(
                model='qwen-plus',
                messages=formatted,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception:
            current_app.logger.exception('Qwen API call failed')
            return None

    def parse_json_response(self, response_text):
        """Try to extract JSON from the response text."""
        if not response_text:
            return None
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to find a JSON block
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1:
                try:
                    return json.loads(response_text[start:end + 1])
                except json.JSONDecodeError:
                    return None
            return None


class DeepSeekProvider:
    """Provider for DeepSeek API (OpenAI-compatible)."""

    def __init__(self, api_key, base_url=None):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                'openai 包未安装，请执行: pip install openai'
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or 'https://api.deepseek.com',
        )

    def chat(self, messages, max_tokens=4096, system=None):
        """Send a chat request to DeepSeek API.

        Args:
            messages: List of dicts with 'role' and 'content'.
            max_tokens: Maximum tokens in response.
            system: Optional system prompt (inserted as first message).

        Returns:
            The text content of the response, or None on error.
        """
        try:
            formatted = []
            if system:
                formatted.append({'role': 'system', 'content': system})
            for msg in messages:
                formatted.append({'role': msg['role'], 'content': msg['content']})

            response = self.client.chat.completions.create(
                model='deepseek-chat',
                messages=formatted,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception:
            current_app.logger.exception('DeepSeek API call failed')
            return None

    def parse_json_response(self, response_text):
        """Try to extract JSON from the response text."""
        if not response_text:
            return None
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1:
                try:
                    return json.loads(response_text[start:end + 1])
                except json.JSONDecodeError:
                    return None
            return None


def get_ai_provider():
    """Get the configured AI provider instance.

    Returns:
        A provider instance (ClaudeProvider or QwenProvider), or None if not configured.
    """
    provider_name = current_app.config.get('AI_PROVIDER', '').lower().strip()

    if provider_name == 'claude':
        api_key = current_app.config.get('CLAUDE_API_KEY', '')
        if not api_key:
            return None
        return ClaudeProvider(api_key)

    if provider_name == 'qwen':
        api_key = current_app.config.get('QWEN_API_KEY', '')
        if not api_key:
            return None
        base_url = current_app.config.get('QWEN_BASE_URL')
        return QwenProvider(api_key, base_url)

    if provider_name == 'deepseek':
        api_key = current_app.config.get('DEEPSEEK_API_KEY', '')
        if not api_key:
            return None
        base_url = current_app.config.get('DEEPSEEK_BASE_URL')
        return DeepSeekProvider(api_key, base_url)

    return None
