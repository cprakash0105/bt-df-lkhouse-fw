"""RAG Indexer — Chunks documents and stores in ChromaDB.
Sources indexed:
    - Table configs (YAML)
    - Seed glossary (business terms, BAs, domains)
    - DATA_CATALOGUE.md
    - Pipeline logs (latest reconciliation, DQ summaries)
    - Operational guide

ChromaDB persists to a local directory (can be synced to GCS).
"""
import os
import json
import yaml
from typing import List, Dict
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False

from discovery.engine.rag.embedder import embed_text, embed_batch


# Chunk size in characters (~500 tokens ≈ 2000 chars)
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

# Persist directory
CHROMA_DIR = os.environ.get("CHROMA_PERSIST_DIR", "/tmp/ontika_rag_db")


def get_collection():
    """Get or create the ChromaDB collection."""
    if not HAS_CHROMA:
        raise ImportError("chromadb not installed. Run: pip install chromadb")

    client = chromadb.Client(Settings(
        chroma_db_impl="duckdb+parquet",
        persist_directory=CHROMA_DIR,
        anonymized_telemetry=False,
    ))
    collection = client.get_or_create_collection(
        name="ontika_knowledge",
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def chunk_text(text: str, source: str, metadata: dict = None) -> List[Dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP):
        chunk = text[i:i + CHUNK_SIZE]
        if len(chunk.strip()) < 50:
            continue
        chunks.append({
            "text": chunk,
            "source": source,
            "chunk_index": len(chunks),
            "metadata": metadata or {},
        })
    return chunks


def index_yaml_config(filepath: str) -> List[Dict]:
    """Index a table config YAML as chunks."""
    with open(filepath) as f:
        content = f.read()
    config = yaml.safe_load(content)
    table_name = config.get("table", Path(filepath).stem)

    # Create a readable summary
    summary = f"Table: {table_name}\n"
    summary += f"Description: {config.get('description', '')}\n"
    summary += f"Source format: {config.get('source_format', 'unknown')}\n"
    summary += f"Domain: {config.get('domain', 'unknown')}\n"
    summary += f"Business application: {config.get('business_application', 'unknown')}\n"
    summary += f"Primary key: {config.get('primary_key', 'unknown')}\n"
    summary += f"Is CDC: {config.get('is_cdc', False)}\n"
    summary += f"PII fields: {config.get('pii_fields', [])}\n"
    summary += f"DQ rules: {json.dumps(config.get('dq_rules', {}))}\n"
    summary += f"Hash fields: {config.get('hash_fields', [])}\n"
    summary += f"Full config:\n{content}"

    return chunk_text(summary, source=f"config/{table_name}.yaml",
                      metadata={"type": "table_config", "table": table_name,
                                "domain": config.get("domain", "")})


def index_glossary(filepath: str) -> List[Dict]:
    """Index seed glossary (BAs, domains, terms)."""
    with open(filepath) as f:
        content = f.read()
    glossary = yaml.safe_load(content)

    chunks = []

    # Business applications
    for ba in glossary.get("business_applications", []):
        text = (f"Business Application: {ba['name']} (ID: {ba['id']})\n"
                f"Description: {ba.get('description', '')}\n"
                f"Keywords: {', '.join(ba.get('keywords', []))}")
        chunks.append({"text": text, "source": "glossary/business_applications",
                       "chunk_index": len(chunks),
                       "metadata": {"type": "business_application", "id": ba["id"]}})

    # Domains
    for domain in glossary.get("data_domains", []):
        text = (f"Data Domain: {domain['name']} (ID: {domain['id']})\n"
                f"Description: {domain.get('description', '')}")
        chunks.append({"text": text, "source": "glossary/domains",
                       "chunk_index": len(chunks),
                       "metadata": {"type": "domain", "id": domain["id"]}})

    # Business terms
    for term in glossary.get("business_terms", []):
        text = (f"Business Term: {term['name']} (ID: {term['id']})\n"
                f"Domain: {term.get('domain', '')}\n"
                f"Synonyms: {', '.join(term.get('synonyms', []))}\n"
                f"Data type: {term.get('data_type', '')}\n"
                f"Information type: {term.get('information_type', '')}\n"
                f"Is PII: {term.get('is_pii', False)}\n"
                f"DQ rules: {json.dumps(term.get('dq_rules', {}))}")
        chunks.append({"text": text, "source": "glossary/terms",
                       "chunk_index": len(chunks),
                       "metadata": {"type": "business_term", "id": term["id"],
                                    "domain": term.get("domain", "")}})

    return chunks


def index_markdown(filepath: str) -> List[Dict]:
    """Index a markdown document (DATA_CATALOGUE, DESIGN, OPERATIONAL_GUIDE)."""
    with open(filepath) as f:
        content = f.read()
    filename = Path(filepath).name
    return chunk_text(content, source=f"docs/{filename}",
                      metadata={"type": "documentation", "file": filename})


def index_gcs_logs(bucket_name: str, prefix: str = "logs/") -> List[Dict]:
    """Index latest pipeline logs from GCS."""
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))

        # Get latest log per stage
        latest = {}
        for blob in blobs:
            if blob.name.endswith(".jsonl"):
                stage = blob.name.split("/")[1] if "/" in blob.name else "unknown"
                if stage not in latest or blob.time_created > latest[stage].time_created:
                    latest[stage] = blob

        chunks = []
        for stage, blob in latest.items():
            content = blob.download_as_text()
            lines = content.strip().split("\n")[:50]  # Last 50 log lines
            text = f"Pipeline log ({stage}, latest run):\n" + "\n".join(lines)
            chunks.extend(chunk_text(text, source=f"logs/{stage}",
                                     metadata={"type": "pipeline_log", "stage": stage}))
        return chunks
    except Exception as e:
        print(f"[RAG] GCS log indexing skipped: {e}")
        return []


def build_index(config_dir: str = None, glossary_path: str = None,
                docs_paths: List[str] = None, gcs_bucket: str = None):
    """Build the full RAG index from all sources."""
    print("[RAG] Building index...")

    all_chunks = []

    # 1. Table configs
    if config_dir:
        tables_dir = os.path.join(config_dir, "tables") if not config_dir.endswith("tables") else config_dir
        if os.path.isdir(tables_dir):
            for f in sorted(os.listdir(tables_dir)):
                if f.endswith(".yaml"):
                    all_chunks.extend(index_yaml_config(os.path.join(tables_dir, f)))
            print(f"[RAG] Indexed {len(os.listdir(tables_dir))} table configs")

    # 2. Glossary
    if glossary_path and os.path.exists(glossary_path):
        all_chunks.extend(index_glossary(glossary_path))
        print(f"[RAG] Indexed glossary")

    # 3. Documentation
    if docs_paths:
        for doc_path in docs_paths:
            if os.path.exists(doc_path):
                all_chunks.extend(index_markdown(doc_path))
                print(f"[RAG] Indexed {Path(doc_path).name}")

    # 4. GCS logs
    if gcs_bucket:
        all_chunks.extend(index_gcs_logs(gcs_bucket))

    if not all_chunks:
        print("[RAG] No documents to index")
        return 0

    # Embed all chunks
    print(f"[RAG] Embedding {len(all_chunks)} chunks...")
    texts = [c["text"] for c in all_chunks]
    embeddings = embed_batch(texts)

    # Filter out failed embeddings
    valid = [(c, e) for c, e in zip(all_chunks, embeddings) if e]
    if not valid:
        print("[RAG] All embeddings failed — check Ollama connection")
        return 0

    # Store in ChromaDB
    client, collection = get_collection()

    # Clear existing
    try:
        collection.delete(where={"source": {"$ne": ""}})
    except Exception:
        pass

    # Add in batches
    batch_size = 100
    for i in range(0, len(valid), batch_size):
        batch = valid[i:i + batch_size]
        collection.add(
            ids=[f"chunk_{i + j}" for j in range(len(batch))],
            embeddings=[e for _, e in batch],
            documents=[c["text"] for c, _ in batch],
            metadatas=[{**c.get("metadata", {}), "source": c["source"]} for c, _ in batch],
        )

    client.persist()
    print(f"[RAG] Index built: {len(valid)} chunks stored in ChromaDB")
    return len(valid)
