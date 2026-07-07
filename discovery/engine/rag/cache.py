"""Response Cache — Hybrid exact-hash + semantic similarity cache for LLM responses.

Avoids repeated LLM calls for same/similar questions.
- Exact: MD5 hash of normalised question → instant hit
- Semantic: ChromaDB cosine similarity > threshold → near-match hit
- Persistence: Firestore (survives restarts), ChromaDB in-memory (fast lookup)
"""
import hashlib
import json
import os
import re
import time
from typing import Optional, Tuple

from discovery.engine.rag.embedder import embed_text
from discovery.engine.rag.indexer import HAS_CHROMA

# Semantic similarity threshold (0.92 = very similar questions match)
SIMILARITY_THRESHOLD = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.92"))
# Cache TTL in seconds (24 hours default)
CACHE_TTL = int(os.environ.get("CACHE_TTL", "86400"))

_client = None
_collection = None
_exact_cache = {}  # in-memory hash → {answer, timestamp}
_fs_client = None


def _get_chroma():
    """Get or create the qa_cache ChromaDB collection."""
    global _client, _collection
    if _collection is not None:
        return _collection
    if not HAS_CHROMA:
        return None
    try:
        import chromadb
        _client = chromadb.Client()
        _collection = _client.get_or_create_collection(
            name="qa_cache",
            metadata={"hnsw:space": "cosine"},
        )
        return _collection
    except Exception as e:
        print(f"[Cache] ChromaDB init failed: {e}")
        return None


def _get_firestore():
    """Get Firestore client for persistence."""
    global _fs_client
    if _fs_client is not None:
        return _fs_client
    try:
        from google.cloud import firestore
        _fs_client = firestore.Client()
        return _fs_client
    except Exception:
        return None


def _normalise(question: str) -> str:
    """Normalise question for hashing: lowercase, strip punctuation, collapse whitespace."""
    q = question.lower().strip()
    q = re.sub(r'[^\w\s]', '', q)
    q = re.sub(r'\s+', ' ', q)
    return q


def _hash_question(question: str) -> str:
    """MD5 hash of normalised question."""
    return hashlib.md5(_normalise(question).encode()).hexdigest()


def get(question: str) -> Optional[str]:
    """Check cache for a matching answer. Returns answer string or None."""
    now = time.time()

    # 1. Exact hash lookup (instant)
    h = _hash_question(question)
    if h in _exact_cache:
        entry = _exact_cache[h]
        if now - entry["timestamp"] < CACHE_TTL:
            return entry["answer"]
        else:
            del _exact_cache[h]

    # Try Firestore exact match
    fs = _get_firestore()
    if fs:
        try:
            doc = fs.collection("qa_cache").document(h).get()
            if doc.exists:
                data = doc.to_dict()
                if now - data.get("timestamp", 0) < CACHE_TTL:
                    # Warm in-memory cache
                    _exact_cache[h] = data
                    return data["answer"]
        except Exception:
            pass

    # 2. Semantic similarity lookup
    collection = _get_chroma()
    if collection and collection.count() > 0:
        try:
            embedding = embed_text(question)
            results = collection.query(
                query_embeddings=[embedding],
                n_results=1,
                include=["documents", "metadatas", "distances"],
            )
            if results and results["distances"] and results["distances"][0]:
                distance = results["distances"][0][0]
                similarity = 1 - distance
                if similarity >= SIMILARITY_THRESHOLD:
                    answer = results["metadatas"][0][0].get("answer", "")
                    ts = results["metadatas"][0][0].get("timestamp", 0)
                    if now - ts < CACHE_TTL:
                        return answer
        except Exception as e:
            print(f"[Cache] Semantic lookup failed: {e}")

    return None


def put(question: str, answer: str) -> None:
    """Store a Q&A pair in both exact and semantic caches."""
    now = time.time()
    h = _hash_question(question)

    # 1. Exact cache (in-memory)
    _exact_cache[h] = {"answer": answer, "timestamp": now}

    # 2. Firestore persistence
    fs = _get_firestore()
    if fs:
        try:
            fs.collection("qa_cache").document(h).set({
                "question": question,
                "answer": answer,
                "timestamp": now,
                "hash": h,
            })
        except Exception:
            pass

    # 3. Semantic cache (ChromaDB)
    collection = _get_chroma()
    if collection:
        try:
            embedding = embed_text(question)
            collection.upsert(
                ids=[h],
                embeddings=[embedding],
                documents=[question],
                metadatas=[{"answer": answer, "timestamp": now, "hash": h}],
            )
        except Exception as e:
            print(f"[Cache] Semantic store failed: {e}")


def invalidate(question: str = None) -> int:
    """Invalidate cache entries. If question is None, clear all."""
    global _exact_cache
    count = 0

    if question is None:
        count = len(_exact_cache)
        _exact_cache = {}
        collection = _get_chroma()
        if collection and collection.count() > 0:
            try:
                # ChromaDB doesn't have clear(), delete all IDs
                all_ids = collection.get()["ids"]
                if all_ids:
                    collection.delete(ids=all_ids)
                    count += len(all_ids)
            except Exception:
                pass
        fs = _get_firestore()
        if fs:
            try:
                docs = fs.collection("qa_cache").stream()
                for doc in docs:
                    doc.reference.delete()
            except Exception:
                pass
    else:
        h = _hash_question(question)
        if h in _exact_cache:
            del _exact_cache[h]
            count += 1
        collection = _get_chroma()
        if collection:
            try:
                collection.delete(ids=[h])
                count += 1
            except Exception:
                pass

    return count


def stats() -> dict:
    """Return cache statistics."""
    collection = _get_chroma()
    semantic_count = collection.count() if collection else 0
    return {
        "exact_entries": len(_exact_cache),
        "semantic_entries": semantic_count,
        "ttl_seconds": CACHE_TTL,
        "similarity_threshold": SIMILARITY_THRESHOLD,
    }
