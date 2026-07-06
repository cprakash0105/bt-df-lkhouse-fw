"""LLM Client — Minimal, token-optimized.
Supports: AWS Bedrock Mantle (OpenAI-compatible) or any OpenAI-compatible API.
Loads config from .env file via python-dotenv."""
import os
import json
import urllib.request
from pathlib import Path
from typing import Optional

# Load .env from discovery/ directory
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass


class LLMClient:
    """LLM client using OpenAI-compatible REST API. Works with Bedrock Mantle and Ollama."""

    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "bedrock")
        self.model = os.environ.get("LLM_MODEL", "openai.gpt-oss-120b")
        self.base_url = os.environ.get("LLM_BASE_URL", "https://bedrock-mantle.eu-north-1.api.aws/v1")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.project = os.environ.get("LLM_PROJECT", "default")

    def generate(self, system: str, user: str, max_tokens: int = 2048, temperature: float = 0.1) -> Optional[str]:
        """Send a request to the LLM. Returns text response or None."""
        if not self.api_key:
            print("[LLM] No LLM_API_KEY set. Check your .env file.")
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
        if self.project:
            headers["OpenAI-Project"] = self.project

        try:
            req = urllib.request.Request(url, data=payload.encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode())
            msg = result["choices"][0]["message"]
            # Reasoning models put output in 'reasoning' when content is null
            text = msg.get("content") or msg.get("reasoning") or ""
            return self._strip_fences(text.strip())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.readable() else ""
            if e.code == 429 or "quota" in body.lower() or "rate" in body.lower():
                print("[LLM] Rate limit / quota exceeded.")
                return "__QUOTA_EXCEEDED__"
            print(f"[LLM] HTTP {e.code}: {body[:200]}")
            return None
        except Exception as e:
            print(f"[LLM] Failed: {e}")
            return None

    @staticmethod
    def _strip_fences(text: str) -> str:
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return text


# Singleton
_client = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
