"""RAG Embeddings — Uses AWS Bedrock Mantle (OpenAI-compatible) for embeddings.
Falls back to simple TF-IDF hashing if Bedrock unavailable.
"""
import os
import sys
import json
import time
import urllib.request
import hashlib
from typing import List
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from logger import get_logger
_log = get_logger("discovery.rag.embedder")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://bedrock-mantle.eu-north-1.api.aws/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_PROJECT = os.environ.get("LLM_PROJECT", "default")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")


def embed_text(text: str) -> List[float]:
    """Generate embedding via Bedrock Mantle OpenAI-compatible endpoint."""
    url = f"{LLM_BASE_URL}/embeddings"
    payload = json.dumps({"model": EMBED_MODEL, "input": text})

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    if LLM_PROJECT:
        headers["OpenAI-Project"] = LLM_PROJECT

    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=payload.encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        _log.debug("Embedding generated", model=EMBED_MODEL, duration_ms=int((time.time()-t0)*1000))
        return result["data"][0]["embedding"]
    except Exception as e:
        _log.warn("Bedrock embedding failed, using fallback", error=str(e), model=EMBED_MODEL)
        return _fallback_embed(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts."""
    embeddings = []
    for i, text in enumerate(texts):
        emb = embed_text(text)
        embeddings.append(emb)
        if (i + 1) % 50 == 0:
            _log.info("Batch embedding progress", completed=i+1, total=len(texts))
    return embeddings


def _fallback_embed(text: str, dim: int = 256) -> List[float]:
    """Deterministic hash-based embedding fallback (no external deps)."""
    h = hashlib.sha256(text.lower().encode()).digest()
    # Expand hash to desired dimension
    result = []
    for i in range(dim):
        seed = hashlib.md5(h + i.to_bytes(4, "little")).digest()
        val = int.from_bytes(seed[:4], "little") / (2**32) - 0.5
        result.append(val)
    return result
