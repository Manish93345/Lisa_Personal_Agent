"""
LISA — RAG Memory (fixed ChromaDB ids fetch)
"""

import os, time
from pathlib import Path
import chromadb
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Lazy init — prevent crash if GEMINI_API_KEY missing at import time
_gemini_client = None
EMBEDDING_MODEL = "gemini-embedding-001"

BASE_DIR        = Path(__file__).parent.parent
VECTORDB_DIR    = BASE_DIR / "data" / "vectordb"
COLLECTION_NAME = "lisa_chats"

_client     = None
_collection = None

_recent_chunk_ids: list[str] = []
MAX_RECENT = 15


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client     = chromadb.PersistentClient(path=str(VECTORDB_DIR))
        _collection = _client.get_collection(COLLECTION_NAME)
    return _collection


def _embed(text: str):
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        try:
            _gemini_client = genai.Client(api_key=api_key)
        except Exception:
            return None

    for attempt in range(3):
        try:
            r = _gemini_client.models.embed_content(
                model=EMBEDDING_MODEL, contents=text
            )
            return r.embeddings[0].values
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep((attempt + 1) * 3)
            else:
                return None
    return None


def get_style_context(user_message: str, top_k: int = 4) -> str:
    global _recent_chunk_ids

    try:
        collection = _get_collection()
    except Exception as e:
        print(f"[RAG] Load error: {e}")
        return ""

    emb = _embed(user_message)
    if emb is None:
        return ""

    try:
        # ids alag se nahi aata query mein — documents aur distances hi lo
        # ChromaDB results mein order se IDs match karte hain
        results = collection.query(
            query_embeddings = [emb],
            n_results        = top_k * 3,
            include          = ["documents", "distances"]   # ids yahan nahi
        )
    except Exception as e:
        print(f"[RAG] Query error: {e}")
        return ""

    docs  = results.get("documents", [[]])[0]
    dists = results.get("distances",  [[]])[0]

    if not docs:
        return ""

    selected = []

    for doc, dist in zip(docs, dists):
        if len(selected) >= top_k:
            break

        # Too dissimilar — skip
        if dist > 0.75:
            continue

        # Near-duplicate check with already selected
        too_similar = False
        for already in selected:
            overlap = len(
                set(doc[:120].split()) & set(already[:120].split())
            )
            if overlap > 10:
                too_similar = True
                break
        if too_similar:
            continue

        # Recently used check (use doc fingerprint instead of id)
        fingerprint = doc[:60]
        if fingerprint in _recent_chunk_ids:
            continue

        selected.append(doc)
        _recent_chunk_ids.append(fingerprint)

    # Fallback
    if not selected:
        selected = docs[:2]

    # Keep recent list bounded
    _recent_chunk_ids = _recent_chunk_ids[-MAX_RECENT:]

    return (
        "[Past conversation examples — inhi ki tarah style mein reply karna]\n\n"
        + "\n\n".join(selected)
    )


def reset_recent():
    global _recent_chunk_ids
    _recent_chunk_ids = []