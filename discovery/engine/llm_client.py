"""LLM Client — Minimal, token-optimized, works with any OpenAI-compatible API.
Supports: Perplexity, Gemini, OpenAI, Groq, Together, etc.
Uses only urllib — zero external dependencies."""
import os
import json
import urllib.request
from typing import Optional


class LLMClient:
    """Minimal LLM client using OpenAI-compatible REST API."""

    def __init__(self):
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL", "https://api.perplexity.ai")
        self.model = os.environ.get("LLM_MODEL", "sonar")

    def generate(self, system: str, user: str, max_tokens: int = 2048, temperature: float = 0.1) -> Optional[str]:
        """Send a request to the LLM. Returns text response or None."""
        if not self.api_key:
            print("[LLM] No API key set (LLM_API_KEY)")
            return None

        url = f"{self.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        })

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            req = urllib.request.Request(url, data=payload.encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())

            text = result["choices"][0]["message"]["content"].strip()

            # Strip markdown code fences
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines).strip()

            return text

        except Exception as e:
            print(f"[LLM] Failed: {e}")
            return None


# Singleton
_client = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
