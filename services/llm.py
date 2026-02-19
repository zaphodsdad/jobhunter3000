"""
LLM abstraction — dispatches to OpenRouter, Google Gemini, or Ollama based on settings.
"""

import httpx
from openai import OpenAI
import google.generativeai as genai


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

    elif provider == "google":
        genai.configure(api_key=settings.get("google_api_key", ""))
        model = genai.GenerativeModel(settings.get("google_model", "gemini-2.0-flash"))

        # Convert OpenAI-style messages to Gemini format
        # Gemini wants: [{"role": "user"|"model", "parts": ["text"]}]
        # System messages get prepended to the first user message
        system_text = ""
        gemini_history = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_text += content + "\n\n"
            elif role == "assistant":
                gemini_history.append({"role": "model", "parts": [content]})
            else:  # user
                text = (system_text + content) if system_text else content
                system_text = ""
                gemini_history.append({"role": "user", "parts": [text]})

        # Start chat with history (all but last message), send last message
        if len(gemini_history) > 1:
            chat = model.start_chat(history=gemini_history[:-1])
            response = chat.send_message(gemini_history[-1]["parts"][0])
        else:
            chat = model.start_chat()
            response = chat.send_message(gemini_history[0]["parts"][0])

        return response.text

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
