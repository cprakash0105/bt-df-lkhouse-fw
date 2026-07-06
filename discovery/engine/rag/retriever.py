"""RAG Retriever — Queries ChromaDB and augments LLM prompts with relevant context.
Called by the KC agent or directly from the API when answering questions.
"""
import os
from typing import List, Dict, Optional

from discovery.engine.rag.embedder import embed_text
from discovery.engine.rag.indexer import get_collection, HAS_CHROMA
from discovery.engine.llm_client import get_llm


# Number of chunks to retrieve
TOP_K = int(os.environ.get("RAG_TOP_K", "5"))

# System prompt for RAG-augmented answers
RAG_SYSTEM_PROMPT = """You are Ontika, an intelligent data operations assistant for the BT Data Fabric.
You have access to retrieved context from the knowledge base. Use ONLY the provided context to answer.
If the context doesn't contain enough information, say so clearly.
Be concise, specific, and use markdown formatting.
When citing data, reference the source (e.g. table config, glossary, pipeline log)."""


class RAGRetriever:
    """Retrieves relevant context from ChromaDB and generates augmented answers."""

    def __init__(self):
        self._collection = None
        self._available = False
        try:
            if HAS_CHROMA:
                _, self._collection = get_collection()
                count = self._collection.count()
                self._available = count > 0
                print(f"[RAG] Retriever ready ({count} chunks indexed)")
            else:
                print("[RAG] ChromaDB not installed — RAG disabled")
        except Exception as e:
            print(f"[RAG] Retriever init failed: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    def retrieve(self, query: str, top_k: int = None, filter_type: str = None) -> List[Dict]:
        """Retrieve top-K relevant chunks for a query."""
        if not self._available:
            return []

        k = top_k or TOP_K

        # Embed the query
        query_embedding = embed_text(query)
        if not query_embedding:
            return []

        # Build where filter
        where = None
        if filter_type:
            where = {"type": filter_type}

        # Query ChromaDB
        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"[RAG] Query failed: {e}")
            return []

        # Format results
        chunks = []
        if results and results["documents"]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                chunks.append({
                    "text": doc,
                    "source": meta.get("source", "unknown"),
                    "type": meta.get("type", "unknown"),
                    "relevance": round(1 - dist, 3),  # cosine distance → similarity
                })

        return chunks

    def answer(self, question: str, filter_type: str = None) -> str:
        """Full RAG pipeline: retrieve context → augment prompt → generate answer."""
        # 1. Retrieve relevant chunks
        chunks = self.retrieve(question, filter_type=filter_type)

        if not chunks:
            # Fallback to plain LLM
            llm = get_llm()
            response = llm.generate(
                system="You are Ontika, a data operations assistant. Answer concisely.",
                user=question,
            )
            return response or "I couldn't find relevant information. Try rephrasing your question."

        # 2. Build context string
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[Source {i}: {chunk['source']} (relevance: {chunk['relevance']})]\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # 3. Augmented prompt
        augmented_user = (
            f"Context from knowledge base:\n\n{context}\n\n"
            f"---\n\n"
            f"Question: {question}\n\n"
            f"Answer based on the context above. Be specific and cite sources."
        )

        # 4. Generate
        llm = get_llm()
        response = llm.generate(
            system=RAG_SYSTEM_PROMPT,
            user=augmented_user,
            max_tokens=1024,
            temperature=0.1,
        )

        if not response or response == "__QUOTA_EXCEEDED__":
            # Return raw context as fallback
            return f"Here's what I found:\n\n" + "\n\n".join(
                f"**{c['source']}** (relevance: {c['relevance']}):\n{c['text'][:300]}..."
                for c in chunks[:3]
            )

        return response

    def get_context_for_prompt(self, question: str, max_chars: int = 3000) -> str:
        """Retrieve context string to inject into an existing prompt (for KC agent use)."""
        chunks = self.retrieve(question)
        if not chunks:
            return ""

        context = ""
        for chunk in chunks:
            addition = f"\n[{chunk['source']}]: {chunk['text']}\n"
            if len(context) + len(addition) > max_chars:
                break
            context += addition

        return context


# Singleton
_retriever: Optional[RAGRetriever] = None


def get_retriever() -> RAGRetriever:
    global _retriever
    if _retriever is None:
        _retriever = RAGRetriever()
    return _retriever
