"""Embedder — Semantic matching via embeddings.
Uses Vertex AI text-embedding-005 in GCP, falls back to sentence-transformers locally."""
import os
import numpy as np
from typing import Optional
from dataclasses import dataclass

# Lazy imports for flexibility
_vertex_available = False
_local_model = None


@dataclass
class EmbeddingMatch:
    term_id: str
    term_name: str
    similarity: float
    domain: str


class Embedder:
    """Hybrid embedder: Vertex AI (GCP) or sentence-transformers (local)."""

    def __init__(self, mode: str = "auto", project_id: Optional[str] = None, region: str = "europe-west2"):
        """
        mode: 'vertex' | 'local' | 'auto'
        auto: tries Vertex AI, falls back to local
        """
        self.mode = mode
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID")
        self.region = region
        self._embeddings_cache: dict[str, np.ndarray] = {}
        self._term_embeddings: dict[str, np.ndarray] = {}
        self._initialized = False

    def initialize(self, terms: list[dict]):
        """Pre-compute embeddings for all business terms in the knowledge graph."""
        if self._initialized:
            return

        if self.mode == "auto":
            self.mode = self._detect_mode()

        # Build text representations for each term
        term_texts = {}
        for term in terms:
            text = self._term_to_text(term)
            term_texts[term["id"]] = text

        # Batch embed all terms
        texts = list(term_texts.values())
        ids = list(term_texts.keys())

        embeddings = self._embed_batch(texts)
        for term_id, embedding in zip(ids, embeddings):
            self._term_embeddings[term_id] = embedding

        self._initialized = True

    def find_similar_terms(self, field_name: str, field_type: str = "string",
                           description: str = "", top_k: int = 3,
                           threshold: float = 0.4) -> list[EmbeddingMatch]:
        """Find most similar business terms for a given field."""
        if not self._initialized:
            return []

        query_text = f"{field_name.replace('_', ' ')} {field_type} {description}".strip()
        query_embedding = self._embed_single(query_text)

        similarities = []
        for term_id, term_embedding in self._term_embeddings.items():
            sim = self._cosine_similarity(query_embedding, term_embedding)
            if sim >= threshold:
                similarities.append((term_id, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return [
            EmbeddingMatch(term_id=tid, term_name=tid, similarity=round(sim, 3), domain="")
            for tid, sim in similarities[:top_k]
        ]

    def _term_to_text(self, term: dict) -> str:
        """Convert a business term to searchable text."""
        parts = [
            term.get("name", ""),
            " ".join(term.get("synonyms", [])),
            term.get("data_type", ""),
            term.get("information_type", ""),
            term.get("domain", ""),
        ]
        return " ".join(p for p in parts if p).lower()

    def _embed_single(self, text: str) -> np.ndarray:
        if text in self._embeddings_cache:
            return self._embeddings_cache[text]
        result = self._embed_batch([text])[0]
        self._embeddings_cache[text] = result
        return result

    def _embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if self.mode == "vertex":
            return self._embed_vertex(texts)
        return self._embed_local(texts)

    def _embed_vertex(self, texts: list[str]) -> list[np.ndarray]:
        """Use Vertex AI text-embedding-005."""
        try:
            from vertexai.language_models import TextEmbeddingModel
            import vertexai

            vertexai.init(project=self.project_id, location=self.region)
            model = TextEmbeddingModel.from_pretrained("text-embedding-005")

            # Vertex AI batch limit is 250
            all_embeddings = []
            for i in range(0, len(texts), 250):
                batch = texts[i:i + 250]
                embeddings = model.get_embeddings(batch)
                all_embeddings.extend([np.array(e.values) for e in embeddings])

            return all_embeddings
        except Exception as e:
            print(f"Vertex AI embedding failed, falling back to local: {e}")
            return self._embed_local(texts)

    def _embed_local(self, texts: list[str]) -> list[np.ndarray]:
        """Fallback: use sentence-transformers locally."""
        global _local_model
        if _local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                _local_model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                # Ultimate fallback: TF-IDF style hashing
                return self._embed_tfidf(texts)

        embeddings = _local_model.encode(texts, show_progress_bar=False)
        return [np.array(e) for e in embeddings]

    def _embed_tfidf(self, texts: list[str]) -> list[np.ndarray]:
        """Minimal fallback: character n-gram hashing (no ML dependencies)."""
        dim = 128
        embeddings = []
        for text in texts:
            vec = np.zeros(dim)
            tokens = text.lower().replace("_", " ").split()
            for token in tokens:
                for i in range(len(token) - 2):
                    ngram = token[i:i + 3]
                    idx = hash(ngram) % dim
                    vec[idx] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)
        return embeddings

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def _detect_mode(self) -> str:
        """Auto-detect if Vertex AI is available."""
        try:
            import vertexai  # noqa: F401
            if self.project_id:
                return "vertex"
        except ImportError:
            pass
        return "local"
