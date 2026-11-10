"""AI provider abstraction layer for Claude, Qwen and DeepSeek (OpenAI-compatible)."""

import json
from flask import current_app


class ClaudeProvider:
    """Provider for Anthropic Claude API."""

    def __init__(self, api_key, model=None, timeout=60):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key, timeout=timeout)
        self.model = model or 'claude-sonnet-4-20250514'

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
                model=self.model,
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

    def __init__(self, api_key, base_url=None, model=None, timeout=60):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                'openai 包未安装，请执行: pip install openai'
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            timeout=timeout,
        )
        self.model = model or 'qwen-plus'

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
                model=self.model,
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

    def __init__(self, api_key, base_url=None, model=None, timeout=60):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                'openai 包未安装，请执行: pip install openai'
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or 'https://api.deepseek.com',
            timeout=timeout,
        )
        self.model = model or 'deepseek-chat'

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
                model=self.model,
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


def get_ai_provider(timeout=None):
    """Get the configured AI provider instance.

    Args:
        timeout: 单次请求超时秒数。None 表示使用各驱动的默认值（60 秒）；
                 长文本生成（月度报告）可显式放宽。

    Returns:
        A provider instance, or None if AI_PROVIDER is not configured.
    """
    provider_name = (current_app.config.get('AI_PROVIDER') or '').lower().strip()
    extra = {} if timeout is None else {'timeout': timeout}

    if provider_name == 'claude':
        api_key = current_app.config.get('CLAUDE_API_KEY', '')
        if not api_key:
            return None
        model = current_app.config.get('CLAUDE_MODEL')
        return ClaudeProvider(api_key, model=model, **extra)

    if provider_name == 'qwen':
        api_key = current_app.config.get('QWEN_API_KEY', '')
        if not api_key:
            return None
        base_url = current_app.config.get('QWEN_BASE_URL')
        model = current_app.config.get('QWEN_MODEL')
        return QwenProvider(api_key, base_url, model=model, **extra)

    if provider_name == 'deepseek':
        api_key = current_app.config.get('DEEPSEEK_API_KEY', '')
        if not api_key:
            return None
        base_url = current_app.config.get('DEEPSEEK_BASE_URL')
        model = current_app.config.get('DEEPSEEK_MODEL')
        return DeepSeekProvider(api_key, base_url, model=model, **extra)

    return None
