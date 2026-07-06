"""Ollama Embeddings — Uses the existing Gemma2 instance for embeddings.
Endpoint: POST http://{host}:11434/api/embeddings
Zero cost — runs on the Azure VM already deployed.
"""
import os
import json
import urllib.request
from typing import List


OLLAMA_HOST = os.environ.get("LLM_BASE_URL", "http://4.242.19.167:11434").rstrip("/v1").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemma2:latest")


def embed_text(text: str) -> List[float]:
    """Generate embedding for a single text using Ollama."""
    url = f"{OLLAMA_HOST}/api/embeddings"
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text})

    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        return result["embedding"]
    except Exception as e:
        print(f"[RAG] Embedding failed: {e}")
        return []


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts. Sequential (Ollama doesn't batch natively)."""
    embeddings = []
    for i, text in enumerate(texts):
        emb = embed_text(text)
        embeddings.append(emb)
        if (i + 1) % 50 == 0:
            print(f"[RAG] Embedded {i + 1}/{len(texts)}")
    return embeddings
