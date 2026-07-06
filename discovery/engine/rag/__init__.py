"""Ontika RAG — Lightweight Retrieval-Augmented Generation.
Uses ChromaDB (in-memory, GCS-persisted) + Ollama embeddings (Gemma2).
Zero external cost — runs on existing infrastructure.

Architecture:
    Index time (on deploy / refresh):
        - Table configs, seed glossary, DATA_CATALOGUE, pipeline logs
        - Chunked → embedded via Ollama → stored in ChromaDB

    Query time:
        - Embed user question via Ollama
        - Retrieve top-K relevant chunks
        - Inject into LLM prompt as context
        - Generate grounded answer
"""
