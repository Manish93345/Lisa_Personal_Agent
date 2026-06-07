"""
LISA — Chat Embedder (Gemini + Resume Support)
================================================
Roz chalao jab tak complete na ho — already embedded chunks skip karega.

Usage:
    cd D:\\Study\\LISA_Agent
    python training/embedder.py

Day 1: chunks 0-999 embed honge
Day 2: baki chunks embed honge
"""

import json
import time
from pathlib import Path
from dotenv import load_dotenv
import os

import chromadb
from google import genai

# ── Setup ──────────────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("\n  ERROR: GEMINI_API_KEY not found in .env file\n")
    exit(1)

gemini_client   = genai.Client(api_key=GEMINI_API_KEY)
EMBEDDING_MODEL = "gemini-embedding-001"

BASE_DIR     = Path(__file__).parent.parent
CLEANED_FILE = BASE_DIR / "training" / "data" / "cleaned" / "combined_cleaned.json"
VECTORDB_DIR = BASE_DIR / "data" / "vectordb"

VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
chroma_client   = chromadb.PersistentClient(path=str(VECTORDB_DIR))
COLLECTION_NAME = "lisa_chats"


# ── Embed one chunk ────────────────────────────────────────────────────
def get_embedding(text: str) -> list[float] | None:
    for attempt in range(3):
        try:
            result = gemini_client.models.embed_content(
                model    = EMBEDDING_MODEL,
                contents = text
            )
            return result.embeddings[0].values
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                # Daily quota khatam — stop gracefully
                return "QUOTA_DONE"
            else:
                print(f"  Error: {e}")
                time.sleep(3)
    return None


# ── Chunking ───────────────────────────────────────────────────────────
def make_chunks(turns: list[dict], window: int = 4) -> list[dict]:
    chunks = []
    for i in range(0, len(turns) - window + 1, 2):
        window_turns = turns[i : i + window]
        text_block   = "\n".join(
            f"{t['speaker'].upper()}: {t['text']}"
            for t in window_turns
        )
        chunks.append({
            "id"  : f"chunk_{i}",
            "text": text_block,
            "metadata": {"start_idx": i}
        })
    return chunks


# ── Main ───────────────────────────────────────────────────────────────
def embed_all():
    if not CLEANED_FILE.exists():
        print(f"\n  ERROR: {CLEANED_FILE} nahi mili! Pehle clean_chats.py run karo.\n")
        exit(1)

    with open(CLEANED_FILE, 'r', encoding='utf-8') as f:
        turns = json.load(f)

    chunks = make_chunks(turns, window=4)
    total  = len(chunks)

    print(f"\n  Total chunks : {total}")

    # Get or create collection (NEVER delete — resume support)
    existing_names = [c.name for c in chroma_client.list_collections()]
    if COLLECTION_NAME in existing_names:
        collection    = chroma_client.get_collection(COLLECTION_NAME)
        already_done  = collection.count()
        print(f"  Already done : {already_done} chunks (resuming from here)")
    else:
        collection   = chroma_client.create_collection(
            name     = COLLECTION_NAME,
            metadata = {"hnsw:space": "cosine"}
        )
        already_done = 0
        print(f"  Fresh start  : 0 chunks done")

    # Find which chunk IDs are already embedded
    if already_done > 0:
        existing_ids = set(
            collection.get(include=[])["ids"]
        )
    else:
        existing_ids = set()

    # Filter to only pending chunks
    pending = [c for c in chunks if c["id"] not in existing_ids]
    print(f"  Pending      : {len(pending)} chunks")
    print(f"  Daily limit  : ~1000 requests\n")

    if not pending:
        print("  Sab chunks already embedded hain!")
        print(f"  Total in DB: {collection.count()}")
        return

    done    = 0
    saved   = 0
    quota_hit = False

    for chunk in pending:
        emb = get_embedding(chunk["text"])

        if emb == "QUOTA_DONE":
            print(f"\n  Daily quota khatam!  Aaj ke liye bas.")
            print(f"  Kal dobara run karna — wahan se shuru hoga jahan chhoda.")
            quota_hit = True
            break

        if emb is None:
            continue

        collection.add(
            ids        = [chunk["id"]],
            embeddings = [emb],
            documents  = [chunk["text"]],
            metadatas  = [chunk["metadata"]]
        )
        saved += 1
        done  += 1

        if done % 50 == 0:
            total_now = collection.count()
            pct       = (total_now / total) * 100
            print(f"  Progress: {total_now}/{total} ({pct:.0f}%) embedded")

        time.sleep(0.1)  # small breathing room

    total_now = collection.count()
    pct       = (total_now / total) * 100

    print(f"\n  {'='*50}")
    if quota_hit:
        print(f"  Aaj completed : {saved} new chunks")
        print(f"  Total so far  : {total_now}/{total} ({pct:.0f}%)")
        print(f"  Kal run karo to complete the rest.")
    else:
        print(f"  COMPLETE! Sab {total_now} chunks embedded.")
    print(f"  Location      : {VECTORDB_DIR}")
    print(f"  {'='*50}\n")


if __name__ == "__main__":
    embed_all()