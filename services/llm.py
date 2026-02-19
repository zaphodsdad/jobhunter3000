"""
LLM abstraction — dispatches to OpenRouter or Ollama based on settings.
"""

import httpx
from openai import OpenAI


def _get_openrouter_client(settings: dict) -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.get("openrouter_api_key", ""),
    )


def llm_chat(messages: list[dict], settings: dict) -> str:
    """Send messages to LLM, return completion text.

    messages: list of {"role": "system"|"user"|"assistant", "content": "..."}
    settings: from load_settings()
    """
    provider = settings.get("llm_provider", "ollama")

    if provider == "openrouter":
        client = _get_openrouter_client(settings)
        response = client.chat.completions.create(
            model=settings.get("openrouter_model", "anthropic/claude-sonnet-4"),
            messages=messages,
            temperature=0,
        )
        return response.choices[0].message.content

    else:  # ollama
        endpoint = settings.get("ollama_endpoint", "http://localhost:11434")
        model = settings.get("ollama_model", "qwen2.5-coder:32b")
        resp = httpx.post(
            f"{endpoint}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
