"""
LISA — Local Embedder (sentence-transformers migration)
========================================================
Run this ONCE to migrate your training data from Gemini embeddings
to local sentence-transformers embeddings.

Usage (from project root):
    python training/local_embedder.py

What it does:
  - Reads training/data/cleaned/combined_cleaned.json
  - Creates overlapping 4-turn conversation chunks (same as original embedder)
  - Embeds each chunk with paraphrase-multilingual-MiniLM-L12-v2 (local, free)
  - Saves to ChromaDB collection 'lisa_chats_local'
  - First run downloads the model (~450MB, one time only)

After running this, RAG queries drop from ~6 seconds to ~50ms.
The old 'lisa_chats' collection is left untouched as a backup.
"""

import json
import time
from pathlib import Path

import chromadb

BASE_DIR     = Path(__file__).parent.parent
CLEANED_FILE = BASE_DIR / "training" / "data" / "cleaned" / "combined_cleaned.json"
VECTORDB_DIR = BASE_DIR / "data" / "vectordb"
COLLECTION_NAME = "lisa_chats_local"

VECTORDB_DIR.mkdir(parents=True, exist_ok=True)


def make_chunks(turns: list[dict], window: int = 4) -> list[dict]:
    """Same chunking as original embedder — 4-turn sliding window, step 2."""
    chunks = []
    for i in range(0, len(turns) - window + 1, 2):
        window_turns = turns[i : i + window]
        text_block   = "\n".join(
            f"{t['speaker'].upper()}: {t['text']}"
            for t in window_turns
        )
        chunks.append({
            "id":       f"chunk_{i}",
            "text":     text_block,
            "metadata": {"start_idx": i},
        })
    return chunks


def main():
    print("\n  LISA Local Embedder")
    print("  " + "=" * 50)

    if not CLEANED_FILE.exists():
        print(f"\n  ERROR: {CLEANED_FILE} not found!")
        print("  Run training/clean_chats.py first.\n")
        return

    # Load training data
    with open(CLEANED_FILE, "r", encoding="utf-8") as f:
        turns = json.load(f)

    chunks = make_chunks(turns, window=4)
    total  = len(chunks)
    print(f"\n  Total chunks    : {total}")

    # Load sentence-transformers model
    print("\n  Loading embedding model...")
    print("  (First run downloads ~450MB — subsequent runs use cache)")
    t0 = time.perf_counter()
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(
            "paraphrase-multilingual-MiniLM-L12-v2",
            device="cpu",
        )
        print(f"  Model loaded in {(time.perf_counter()-t0)*1000:.0f}ms\n")
    except ImportError:
        print("\n  ERROR: sentence-transformers not installed!")
        print("  Run: pip install sentence-transformers\n")
        return

    # ChromaDB collection
    chroma_client = chromadb.PersistentClient(path=str(VECTORDB_DIR))
    existing_names = [c.name for c in chroma_client.list_collections()]

    if COLLECTION_NAME in existing_names:
        collection   = chroma_client.get_collection(COLLECTION_NAME)
        already_done = collection.count()
        print(f"  Resuming from   : {already_done} existing chunks")
    else:
        collection   = chroma_client.create_collection(
            name     = COLLECTION_NAME,
            metadata = {"hnsw:space": "cosine"},
        )
        already_done = 0
        print("  Fresh start     : 0 chunks embedded")

    # Find pending chunks
    existing_ids = set(collection.get(include=[])["ids"]) if already_done > 0 else set()
    pending      = [c for c in chunks if c["id"] not in existing_ids]
    print(f"  Pending         : {len(pending)} chunks\n")

    if not pending:
        print("  Already complete! Nothing to do.")
        print(f"  Total in DB: {collection.count()} chunks")
        print(f"\n  RAG is ready — queries will use local embeddings (~50ms).\n")
        return

    # Embed in batches for speed
    BATCH_SIZE = 32
    saved      = 0

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start : batch_start + BATCH_SIZE]
        texts = [c["text"] for c in batch]

        try:
            embeddings = model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as e:
            print(f"  Batch embed error: {e}")
            continue

        for chunk, emb in zip(batch, embeddings):
            try:
                collection.add(
                    ids        = [chunk["id"]],
                    embeddings = [emb.tolist()],
                    documents  = [chunk["text"]],
                    metadatas  = [chunk["metadata"]],
                )
                saved += 1
            except Exception as e:
                print(f"  Add error for {chunk['id']}: {e}")

        done_total = collection.count()
        pct = (done_total / total) * 100
        print(f"  Progress: {done_total}/{total} ({pct:.0f}%)")

    print(f"\n  {'=' * 50}")
    print(f"  COMPLETE! {collection.count()} chunks embedded locally.")
    print(f"  Location : {VECTORDB_DIR}/{COLLECTION_NAME}")
    print(f"\n  RAG queries will now be ~50ms instead of ~6 seconds.")
    print(f"  Restart web_server.py to use the new collection.\n")


if __name__ == "__main__":
    main()