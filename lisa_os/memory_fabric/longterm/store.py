"""
lisa_os.memory_fabric.longterm.store — Phase 2.2

THE single, consolidated long-term memory store. Replaces BOTH:
  - memory/memory_db.py's MemoryManager (root lisa_memory.db)
  - memory/long_term.py (data/memory/lisa_memory.db)

One DB file: data/memory_fabric/longterm.sqlite
One schema, category+key unique (adopts long_term.py's better design —
avoids the root db's global-key collisions).

Adds three fields the old schemas didn't have, matching the fact
schema in Blueprint Section 3.2.1:
  - confidence   : how sure we are this fact is current (0.0-1.0)
  - source       : "extracted" | "explicit" | "migrated" — where it came from
  - last_confirmed : separate from "created", so we know if a fact is stale

Function names match the OLD long_term.py as closely as possible on
purpose — most existing call sites just change their import line.
"""
import sqlite3
import re
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/memory_fabric/longterm.sqlite")


def _get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            category       TEXT NOT NULL,
            key            TEXT NOT NULL,
            value          TEXT NOT NULL,
            confidence     REAL NOT NULL DEFAULT 0.9,
            source         TEXT NOT NULL DEFAULT 'extracted',
            created        TEXT NOT NULL,
            last_confirmed TEXT NOT NULL,
            expires_at     TEXT,
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


# ── Write path ────────────────────────────────────────────────────────

def save_memory(category: str, key: str, value: str,
                 source: str = "extracted", confidence: float = 0.9,
                 expires_at: str | None = None):
    """Upsert by (category, key). Keeps original 'created' on update,
    always bumps 'last_confirmed'.

    General data-integrity guard (not tied to any one caller): rejects
    empty/None values with a clear Python error instead of letting a
    raw sqlite NOT NULL crash bubble up from wherever this got called."""
    if not key or not isinstance(key, str) or not key.strip():
        raise ValueError(f"save_memory: key must be a non-empty string, got {key!r}")
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"save_memory: value must be a non-empty string, got {value!r} (key={key!r})")

    now = datetime.now().isoformat()
    # ... (baaki function same rahega)
    conn = _get_conn()
    conn.execute("""
        INSERT INTO facts (category, key, value, confidence, source, created, last_confirmed, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(category, key) DO UPDATE SET
            value = excluded.value,
            confidence = excluded.confidence,
            source = excluded.source,
            last_confirmed = excluded.last_confirmed,
            expires_at = excluded.expires_at
    """, (category, key, value, confidence, source, now, now, expires_at))
    conn.commit()
    conn.close()


def delete_memory(category: str, key: str):
    conn = _get_conn()
    conn.execute("DELETE FROM facts WHERE category=? AND key=?", (category, key))
    conn.commit()
    conn.close()


def cleanup_expired():
    now = datetime.now().isoformat()
    conn = _get_conn()
    cur = conn.execute("DELETE FROM facts WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted:
        print(f"  [Memory] Cleaned up {deleted} expired fact(s).")
    return deleted


def save_session_summary(summary: str):
    conn = _get_conn()
    conn.execute("INSERT INTO sessions (summary, timestamp) VALUES (?, ?)",
                 (summary, datetime.now().isoformat()))
    conn.execute("""
        DELETE FROM sessions WHERE id NOT IN (
            SELECT id FROM sessions ORDER BY id DESC LIMIT 20
        )
    """)
    conn.commit()
    conn.close()


# ── Read path ─────────────────────────────────────────────────────────

def _fetch_all():
    conn = _get_conn()
    cleanup_expired()
    rows = conn.execute(
        "SELECT category, key, value FROM facts ORDER BY category"
    ).fetchall()
    sums = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return rows, sums


CORE_CATEGORIES = {"personal"}
PAST_REFERENCE_WORDS = {
    "yaad", "kal", "pichle", "wo", "tha", "thi", "the",
    "remember", "previously", "last time", "us din",
    "wo wala", "wo baat", "kabhi",
}


def _score_match(query_words: set, key: str, value: str) -> int:
    text_words = set(re.findall(r"\w+", (key + " " + value).lower()))
    return len(query_words & text_words)


def get_relevant_memories(user_query: str, top_k: int = 3) -> str:
    """Unchanged logic from the old long_term.py (it was good code) —
    just reads from the unified table now."""
    MAX_CORE_FACTS = 20

    rows, sums = _fetch_all()
    if not rows and not sums:
        return ""

    query_lower = user_query.lower()
    query_words = set(re.findall(r"\w+", query_lower))

    core_facts, other_facts = [], []
    for cat, key, val in rows:
        if cat in CORE_CATEGORIES:
            core_facts.append((cat, key, val))
        else:
            score = _score_match(query_words, key, val)
            other_facts.append((score, cat, key, val))

    core_facts = core_facts[-MAX_CORE_FACTS:]
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

    if any(w in query_lower for w in PAST_REFERENCE_WORDS) and sums:
        lines.append("\nPAST SESSION (most recent):")
        summary, ts = sums[0]
        lines.append(f"  [{ts[:10]}] {summary}")

    return "\n".join(lines)


def get_all_memories(user_query: str = "") -> str:
    if user_query:
        return get_relevant_memories(user_query, top_k=5)
    return get_full_memories()


def get_full_memories() -> str:
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


def get_all_active_memories() -> list[dict]:
    """Shape-compatible with the OLD MemoryManager.get_all_active_memories()
    — so core/agent.py's _get_active_memory_context() needs zero changes
    beyond the import line."""
    cleanup_expired()
    conn = _get_conn()
    rows = conn.execute("SELECT key, value, category FROM facts").fetchall()
    conn.close()
    return [{"key": r[0], "value": r[1], "category": r[2]} for r in rows]


def list_all() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT category, key, value, confidence, source, created, last_confirmed FROM facts"
    ).fetchall()
    conn.close()
    return [
        {"category": r[0], "key": r[1], "value": r[2], "confidence": r[3],
         "source": r[4], "created": r[5], "last_confirmed": r[6]}
        for r in rows
    ]


def known_keys_by_category() -> dict:
    """NEW — used by the improved extractor prompt (Phase 2's fix for
    the duplicate-key problem) so the LLM sees what already exists and
    updates it instead of inventing 'spouse_name' vs 'wife_name' again."""
    conn = _get_conn()
    rows = conn.execute("SELECT category, key FROM facts").fetchall()
    conn.close()
    out: dict = {}
    for cat, key in rows:
        out.setdefault(cat, []).append(key)
    return out


def get_recent_sessions(n: int = 3) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [{"summary": r[0], "timestamp": r[1]} for r in rows]


# ── Backward-compat adapter ─────────────────────────────────────────
# main.py and web_server.py both call `agent.memory_manager.<method>()`
# directly (not just core/agent.py's own internals) — Phase 1's rule
# was "old CLI + voice both work unchanged". Rather than edit three
# files to match three slightly-different old APIs, core/agent.py's
# self.memory_manager now points at ONE of these instead of the old
# MemoryManager() class. Same method names, same call shape — nothing
# else needs to know the storage underneath changed.
class LegacyMemoryManagerAdapter:
    def get_all_active_memories(self) -> list[dict]:
        return get_all_active_memories()

    def upsert_memory(self, key: str, value: str, category: str = "general",
                       expires_at: str | None = None):
        save_memory(category, key, value, source="explicit", expires_at=expires_at)

    def delete_memory(self, key: str):
        """Old callers only ever pass `key` (root db had globally-unique
        keys). New schema is (category, key) unique, so look up which
        category(ies) this key lives under and delete all matches."""
        conn = _get_conn()
        rows = conn.execute("SELECT category FROM facts WHERE key=?", (key,)).fetchall()
        conn.close()
        for (cat,) in rows:
            delete_memory(cat, key)

    def cleanup_expired(self):
        return cleanup_expired()