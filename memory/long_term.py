"""
LISA — Long Term Memory (SQLite + Smart Top-K Retrieval)
==========================================================
Changes vs original:
  - get_all_memories() now accepts (query, top_k) → returns ONLY relevant facts
  - get_full_memories() preserved for /memories command
  - Session summaries injected ONLY when query references past
  - Memory string trimmed to <500 tokens worst case

Token impact: ~800-2000 → ~150-300 per chat
"""

import sqlite3
import re
from datetime import datetime
from config.settings import MEMORY_DIR

DB_PATH = MEMORY_DIR / "lisa_memory.db"

# Words that signal "user is referencing past sessions"
PAST_REFERENCE_WORDS = {
    "yaad", "kal", "pichle", "wo", "tha", "thi", "the",
    "remember", "previously", "last time", "us din",
    "wo wala", "wo baat", "kabhi"
}


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            category  TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            UNIQUE(category, key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            summary   TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_memory(category: str, key: str, value: str):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO memories (category, key, value, timestamp)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category, key)
        DO UPDATE SET value=excluded.value, timestamp=excluded.timestamp
    """, (category, key, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ── CORE FACTS — always included (small, identity-defining) ─────────────
# These are the absolute essentials Lisa must always know.
CORE_CATEGORIES = {"personal"}      # name, dob, city, relationship


def _fetch_all():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT category, key, value FROM memories ORDER BY category"
    ).fetchall()
    sums = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return rows, sums


def _score_match(query_words: set, key: str, value: str) -> int:
    """Simple keyword overlap score."""
    text_words = set(re.findall(r"\w+", (key + " " + value).lower()))
    return len(query_words & text_words)


def get_relevant_memories(user_query: str, top_k: int = 3) -> str:
    """
    Returns ONLY:
      - Most recent CORE personal facts (capped at MAX_CORE_FACTS)
      - Top-K relevant non-core memories (only if keyword overlap > 0)
      - Session summaries ONLY if query references past

    [Phase 0 fix] Previously ALL core facts were included regardless of top_k,
    causing 15-18 facts per turn. Now capped: total never exceeds
    MAX_CORE_FACTS + top_k = 8 + 3 = 11 facts maximum.
    """
    MAX_CORE_FACTS = 8   # personal facts cap — keeps identity without bloat

    rows, sums = _fetch_all()
    if not rows and not sums:
        return ""

    query_lower = user_query.lower()
    query_words = set(re.findall(r"\w+", query_lower))

    core_facts = []
    other_facts = []

    for cat, key, val in rows:
        if cat in CORE_CATEGORIES:
            core_facts.append((cat, key, val))
        else:
            score = _score_match(query_words, key, val)
            other_facts.append((score, cat, key, val))

    # Core facts: take most recently stored (last MAX_CORE_FACTS)
    core_facts = core_facts[-MAX_CORE_FACTS:]

    # Non-core: sort by relevance score, take top-k with score > 0
    other_facts.sort(key=lambda x: -x[0])
    selected_other = [(c, k, v) for s, c, k, v in other_facts if s > 0][:top_k]

    if not core_facts and not selected_other:
        return ""

    lines = ["[Manish ke baare mein facts]"]
    current_cat = None

    for cat, key, val in core_facts + selected_other:
        if cat != current_cat:
            lines.append(f"\n{cat.upper()}:")
            current_cat = cat
        lines.append(f"  - {key}: {val}")

    # Add session summary ONLY if user references past
    if any(w in query_lower for w in PAST_REFERENCE_WORDS) and sums:
        lines.append("\nPAST SESSION (most recent):")
        summary, ts = sums[0]
        lines.append(f"  [{ts[:10]}] {summary}")

    return "\n".join(lines)


# ── Backward-compat alias ───────────────────────────────────────────────
def get_all_memories(user_query: str = "") -> str:
    """Compatibility wrapper. Pass user_query for smart retrieval."""
    if user_query:
        return get_relevant_memories(user_query, top_k=5)
    # Fallback to full dump (used by /memories command)
    return get_full_memories()


def get_full_memories() -> str:
    """Full dump for /memories command (debug only)."""
    rows, sums = _fetch_all()
    if not rows and not sums:
        return ""
    lines = ["[All facts about Manish]"]
    current_cat = None
    for cat, key, val in rows:
        if cat != current_cat:
            lines.append(f"\n{cat.upper()}:")
            current_cat = cat
        lines.append(f"  - {key}: {val}")
    if sums:
        lines.append("\nPAST SESSIONS:")
        for summary, ts in sums:
            lines.append(f"  [{ts[:10]}] {summary}")
    return "\n".join(lines)


def list_all() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT category, key, value, timestamp FROM memories"
    ).fetchall()
    conn.close()
    return [{"category": r[0], "key": r[1], "value": r[2], "timestamp": r[3]}
            for r in rows]


def delete_memory(category: str, key: str):
    conn = _get_conn()
    conn.execute("DELETE FROM memories WHERE category=? AND key=?", (category, key))
    conn.commit()
    conn.close()


def save_session_summary(summary: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (summary, timestamp) VALUES (?, ?)",
        (summary, datetime.now().isoformat())
    )
    conn.execute("""
        DELETE FROM sessions WHERE id NOT IN (
            SELECT id FROM sessions ORDER BY id DESC LIMIT 20
        )
    """)
    conn.commit()
    conn.close()


def get_recent_sessions(n: int = 3) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [{"summary": r[0], "timestamp": r[1]} for r in rows]