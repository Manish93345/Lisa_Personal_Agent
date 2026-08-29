"""
lisa_os.memory_fabric.longterm.store — Phase 2.2 + 2.5 extension

THE single, consolidated long-term memory store.

New in this pass:
  - fact_history table: every UPDATE/DELETE logs the old value before
    it's overwritten, with a timestamp + optional reason/quote. This
    is what lets Lisa answer "who was my roommate before Aniket?"
    instead of just knowing the current value.
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT NOT NULL,
            key        TEXT NOT NULL,
            old_value  TEXT,
            new_value  TEXT,
            changed_at TEXT NOT NULL,
            reason     TEXT
        )
    """)
    conn.commit()
    return conn


# ── Write path ────────────────────────────────────────────────────────

def save_memory(category: str, key: str, value: str,
                 source: str = "extracted", confidence: float = 0.9,
                 expires_at: str | None = None, reason: str | None = None):
    """Upsert by (category, key). If a different value already exists,
    the OLD value is logged to fact_history before being overwritten."""
    if not key or not isinstance(key, str) or not key.strip():
        raise ValueError(f"save_memory: key must be a non-empty string, got {key!r}")
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"save_memory: value must be a non-empty string, got {value!r} (key={key!r})")

    now = datetime.now().isoformat()
    conn = _get_conn()

    existing = conn.execute(
        "SELECT value FROM facts WHERE category=? AND key=?", (category, key)
    ).fetchone()
    if existing and existing[0] != value:
        conn.execute(
            "INSERT INTO fact_history (category, key, old_value, new_value, changed_at, reason) VALUES (?,?,?,?,?,?)",
            (category, key, existing[0], value, now, reason)
        )

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


def delete_memory(category: str, key: str, reason: str | None = None):
    now = datetime.now().isoformat()
    conn = _get_conn()
    existing = conn.execute(
        "SELECT value FROM facts WHERE category=? AND key=?", (category, key)
    ).fetchone()
    if existing:
        conn.execute(
            "INSERT INTO fact_history (category, key, old_value, new_value, changed_at, reason) VALUES (?,?,?,?,?,?)",
            (category, key, existing[0], None, now, reason)
        )
    conn.execute("DELETE FROM facts WHERE category=? AND key=?", (category, key))
    conn.commit()
    conn.close()


def get_fact_history(category: str, key: str) -> list[dict]:
    """'Who was my roommate before Aniket?' -> this."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT old_value, new_value, changed_at, reason FROM fact_history "
        "WHERE category=? AND key=? ORDER BY id DESC",
        (category, key)
    ).fetchall()
    conn.close()
    return [{"old_value": r[0], "new_value": r[1], "changed_at": r[2], "reason": r[3]} for r in rows]


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
class LegacyMemoryManagerAdapter:
    def get_all_active_memories(self) -> list[dict]:
        return get_all_active_memories()

    def upsert_memory(self, key: str, value: str, category: str = "general",
                       expires_at: str | None = None):
        save_memory(category, key, value, source="explicit", expires_at=expires_at)

    def delete_memory(self, key: str):
        conn = _get_conn()
        rows = conn.execute("SELECT category FROM facts WHERE key=?", (key,)).fetchall()
        conn.close()
        for (cat,) in rows:
            delete_memory(cat, key)

    def cleanup_expired(self):
        return cleanup_expired()