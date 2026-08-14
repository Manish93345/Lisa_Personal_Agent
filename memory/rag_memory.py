"""
LISA — RAG Memory
=================
[Phase 1 Change — Local Embeddings]
  - BEFORE: gemini-embedding-001 cloud API → 6 seconds per query, burns API quota
  - AFTER:  sentence-transformers local model → ~50ms per query, zero quota

  Model: paraphrase-multilingual-MiniLM-L12-v2
    - 384 dimensions, ~450MB one-time download
    - Best for Hinglish (multilingual, 50+ languages including Hindi)

  MIGRATION: Run  python training/local_embedder.py  ONCE.
    Creates collection 'lisa_chats_local' from your existing training data.
    Takes ~30-60 seconds (vs days of API rate limiting).

  FALLBACK: If 'lisa_chats_local' not found, automatically uses old
    'lisa_chats' (Gemini embedding, slow) so nothing breaks immediately.
"""

import os, time
from pathlib import Path
import chromadb
from dotenv import load_dotenv

load_dotenv()

BASE_DIR        = Path(__file__).parent.parent
VECTORDB_DIR    = BASE_DIR / "data" / "vectordb"

# Two collections — local (fast, preferred) and old Gemini (fallback)
LOCAL_COLLECTION  = "lisa_chats_local"  # sentence-transformers 384d
GEMINI_COLLECTION = "lisa_chats"        # old Gemini 768d (fallback only)

_chroma_client = None
_collection    = None
_use_local     = None   # set when collection is first opened

_local_model   = None   # sentence-transformers model (lazy-loaded)
_model_lock    = __import__("threading").Lock()  # prevents double-load race condition

_recent_chunk_ids: list[str] = []
MAX_RECENT = 15


# ── Collection init ────────────────────────────────────────────────────

def _get_collection():
    global _chroma_client, _collection, _use_local
    if _collection is not None:
        return _collection

    _chroma_client = chromadb.PersistentClient(path=str(VECTORDB_DIR))
    names = [c.name for c in _chroma_client.list_collections()]

    # Prefer local collection (sentence-transformers)
    if LOCAL_COLLECTION in names:
        coll = _chroma_client.get_collection(LOCAL_COLLECTION)
        if coll.count() > 0:
            _collection = coll
            _use_local  = True
            return _collection

    # Fallback: old Gemini collection
    if GEMINI_COLLECTION in names:
        _collection = _chroma_client.get_collection(GEMINI_COLLECTION)
        _use_local  = False
        print("  [RAG] Using Gemini collection (slow). Run training/local_embedder.py to migrate.")
        return _collection

    raise RuntimeError(
        "No RAG collection found.\n"
        "Run: python training/local_embedder.py\n"
        "to create the local embedding collection."
    )


from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
import uuid

def ingest_document(collection, markdown_text: str, source_name: str, subject: str = "general"):
    """
    Markdown text ko smartly chunks mein todta hai aur ChromaDB mein save karta hai.
    collection: Tumhara ChromaDB ka collection object
    """
    print(f"  [RAG] Processing and Chunking document: {source_name}...")

    # ── 1. Smart Markdown Splitter (Heading ke hisaab se todega) ──
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    md_header_splits = markdown_splitter.split_text(markdown_text)

    # ── 2. Overlap Splitter (Agar koi section bohot bada ho toh) ──
    # chunk_overlap=150 ensures ki sentences beech se na kat jayein
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    final_splits = text_splitter.split_documents(md_header_splits)

    documents = []
    metadatas = []
    ids = []

    # ── 3. Metadata Tagging ──
    for split in final_splits:
        documents.append(split.page_content)
        
        # Jo metadata Langchain ne nikala (jaise Header 1: "UML") 
        # usme hum apna custom metadata add kar rahe hain
        meta = split.metadata
        meta.update({
            "source": source_name,
            "subject": subject,
            "type": "study_material"
        })
        metadatas.append(meta)
        ids.append(str(uuid.uuid4()))

    # ── 4. Save to Database ──
    if documents:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"  [RAG] ✅ Successfully injected {len(documents)} context chunks from '{source_name}' into Lisa's brain!")
    else:
        print("  [RAG] ⚠️ No text found to save.")

# ── Embedding ──────────────────────────────────────────────────────────

def _get_local_model():
    """
    Load sentence-transformers model with double-checked locking.
    Prevents race condition where startup preload + first RAG query
    both load the model simultaneously (was causing 60s double-load).
    """
    global _local_model
    if _local_model is not None:        # fast path — no lock needed
        return _local_model
    with _model_lock:                   # only one thread loads at a time
        if _local_model is None:        # re-check after acquiring lock
            try:
                from sentence_transformers import SentenceTransformer
                _local_model = SentenceTransformer(
                    "paraphrase-multilingual-MiniLM-L12-v2",
                    device="cpu",
                )
            except ImportError:
                raise RuntimeError("Run: pip install sentence-transformers")
    return _local_model


def _embed_local(text: str) -> list[float] | None:
    """Local embedding — ~50ms, zero quota."""
    try:
        model = _get_local_model()
        emb   = model.encode(text, normalize_embeddings=True)
        return emb.tolist()
    except Exception as e:
        print(f"  [RAG] Local embed error: {e}")
        return None


def _embed_gemini(text: str) -> list[float] | None:
    """Gemini cloud embedding — fallback only (6s, uses quota)."""
    global _gemini_client
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        if not hasattr(_embed_gemini, "_client") or _embed_gemini._client is None:
            _embed_gemini._client = genai.Client(api_key=api_key)
        r = _embed_gemini._client.models.embed_content(
            model="gemini-embedding-001", contents=text
        )
        return r.embeddings[0].values
    except Exception as e:
        if "429" not in str(e):
            print(f"  [RAG] Gemini embed error: {e}")
        return None


def _embed(text: str) -> list[float] | None:
    """Route embedding to local or Gemini based on active collection."""
    _get_collection()                   # ensure _use_local is set
    return _embed_local(text) if _use_local else _embed_gemini(text)


# ── Public API ─────────────────────────────────────────────────────────

def get_style_context(user_message: str, top_k: int = 4) -> str:
    """
    Query ChromaDB for conversation chunks similar to user_message.
    Used by agent.py to inject style/tone context into the system prompt.

    Returns formatted string of past conversation examples (capped by agent.py).
    """
    global _recent_chunk_ids

    try:
        collection = _get_collection()
    except Exception as e:
        print(f"  [RAG] Load error: {e}")
        return ""

    emb = _embed(user_message)
    if emb is None:
        return ""

    try:
        results = collection.query(
            query_embeddings = [emb],
            n_results        = top_k * 3,
            include          = ["documents", "distances"],
        )
    except Exception as e:
        print(f"  [RAG] Query error: {e}")
        return ""

    docs  = results.get("documents", [[]])[0]
    dists = results.get("distances",  [[]])[0]

    if not docs:
        return ""

    selected = []
    for doc, dist in zip(docs, dists):
        if len(selected) >= top_k:
            break

        # Distance threshold (cosine — lower = more similar)
        if dist > 0.75:
            continue

        # Near-duplicate check
        too_similar = any(
            len(set(doc[:120].split()) & set(sel[:120].split())) > 10
            for sel in selected
        )
        if too_similar:
            continue

        # Recently-used check
        fingerprint = doc[:60]
        if fingerprint in _recent_chunk_ids:
            continue

        selected.append(doc)
        _recent_chunk_ids.append(fingerprint)

    # Fallback: just take first 2 if nothing passed filters
    if not selected:
        selected = docs[:2]

    _recent_chunk_ids = _recent_chunk_ids[-MAX_RECENT:]

    return (
        "[Past conversation examples — inhi ki tarah style mein reply karna]\n\n"
        + "\n\n".join(selected)
    )


def get_document_context(query: str, top_k: int = 3) -> str:
    """User query ke liye ChromaDB se top matching PDF text chunks lata hai."""
    try:
        # Apni Chroma collection yahan use karo (e.g., collection, pdf_collection, ya rag_collection)
        collection = _get_collection()
        results = collection.query(
            query_texts=[query],
            n_results=top_k
        )
        
        if results and results.get('documents') and results['documents'][0]:
            # Extracted chunks ko join karke ek single text context banao
            context_text = "\n\n---\n\n".join(results['documents'][0])
            return context_text
        return ""
    except Exception as e:
        print(f"  [RAG Document Retrieval Error]: {e}")
        return ""



def reset_recent():
    global _recent_chunk_ids
    _recent_chunk_ids = []