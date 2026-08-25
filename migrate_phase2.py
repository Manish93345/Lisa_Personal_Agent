"""
migrate_phase2.py — Phase 2.3, ONE-TIME migration

Reads both OLD dbs (read-only, nothing deleted), applies the cleanup
rules we agreed on in chat, writes the result into the NEW unified
store (lisa_os/memory_fabric/longterm/store.py). Run from project
root, once:

    python migrate_phase2.py

Safe to re-run — save_memory() upserts, won't create duplicates.
Old DB files are NOT touched or deleted — delete them yourself once
you've confirmed the new one looks right (see printed report).
"""
import sqlite3
from pathlib import Path
from datetime import datetime

from lisa_os.memory_fabric.longterm import store

ROOT_DB = Path("lisa_memory.db")
LONGTERM_DB = Path("data/memory/lisa_memory.db")

# ── Rules agreed on in chat, specific to your actual data ──────────────

# (category, key) pairs to drop entirely — not facts, extraction noise.
DROP_KEYS = {
    ("personal", "Manish_kisses"),
    ("personal", "smartness_level"),
    ("personal", "dob"),            # mislabeled duplicate of anniversary_date
    ("personal", "special_date"),   # mislabeled duplicate of anniversary_date
}

# Whole categories to drop from long-term (belongs in conversation
# memory, not "forever" facts) — game sessions, one-off pings.
DROP_CATEGORIES = {"incident"}

# old (category, key) -> canonical (category, key). Applied to BOTH dbs.
RENAME_MAP = {
    ("personal", "naam"): ("personal", "name"),
    ("personal", "spouse"): ("personal", "spouse_name"),
    ("personal", "wife_name"): ("personal", "spouse_name"),
    ("personal", "partner_name"): ("personal", "spouse_name"),
    ("relationship", "partner_name"): ("personal", "spouse_name"),
    ("personal", "Manish_wife"): ("personal", "spouse_name"),
    ("personal", "relationship"): ("personal", "relationship_status"),
    ("personal", "relationship_info"): ("family", "has_sibling"),
}

# For canonical keys where multiple source rows disagree, the exact
# winning value (rather than "latest timestamp wins" default) —
# because "latest" alone doesn't capture what YOU confirmed in chat.
CONFLICT_WINNERS = {
    ("academic", "current_semester"): "7th Semester",
    ("personal", "relationship_status"): "Manish aur Lisa ne jeevan se shaadi kiya",
}


def _canonicalize(category: str, key: str) -> tuple:
    return RENAME_MAP.get((category, key), (category, key))


def _read_root():
    if not ROOT_DB.exists():
        return []
    conn = sqlite3.connect(ROOT_DB)
    rows = conn.execute(
        "SELECT category, key, value, last_updated FROM memories"
    ).fetchall()
    conn.close()
    return [("root", cat, key, val, ts) for cat, key, val, ts in rows]


def _read_longterm():
    if not LONGTERM_DB.exists():
        return [], []
    conn = sqlite3.connect(LONGTERM_DB)
    rows = conn.execute(
        "SELECT category, key, value, timestamp FROM memories"
    ).fetchall()
    sums = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id"
    ).fetchall()
    conn.close()
    facts = [("longterm", cat, key, val, ts) for cat, key, val, ts in rows]
    return facts, sums


def migrate():
    print("=" * 60)
    print("PHASE 2.3 — MIGRATING TO CONSOLIDATED STORE")
    print("=" * 60)

    all_rows = _read_root()
    longterm_rows, sessions = _read_longterm()
    all_rows += longterm_rows

    dropped, renamed, written = [], [], []
    by_canonical: dict = {}   # (cat,key) -> (value, timestamp, orig_source)

    for source, cat, key, val, ts in all_rows:
        if (cat, key) in DROP_KEYS or cat in DROP_CATEGORIES:
            dropped.append((source, cat, key, val))
            continue

        ccat, ckey = _canonicalize(cat, key)
        if (ccat, ckey) != (cat, key):
            renamed.append((source, cat, key, ccat, ckey, val))

        prev = by_canonical.get((ccat, ckey))
        if prev is None or (ts or "") > (prev[1] or ""):
            by_canonical[(ccat, ckey)] = (val, ts, source)

    print(f"\nDROPPED ({len(dropped)} rows — noise / one-off incidents):")
    for source, cat, key, val in dropped:
        print(f"  [{source}] {cat}/{key} = {val!r}")

    print(f"\nRENAMED/MERGED ({len(renamed)} rows folded into canonical keys):")
    for source, cat, key, ccat, ckey, val in renamed:
        print(f"  [{source}] {cat}/{key} -> {ccat}/{ckey}  ({val!r})")

    print(f"\nCONFLICT OVERRIDES APPLIED:")
    for (ccat, ckey), winning_value in CONFLICT_WINNERS.items():
        if (ccat, ckey) in by_canonical:
            by_canonical[(ccat, ckey)] = (
                winning_value, datetime.now().isoformat(), "chat-confirmed"
            )
            print(f"  {ccat}/{ckey} = {winning_value!r}  (confirmed in chat, overrides timestamp-based pick)")

    print(f"\nWRITING {len(by_canonical)} facts to {store.DB_PATH} ...")
    for (ccat, ckey), (val, ts, source) in by_canonical.items():
        store.save_memory(ccat, ckey, val, source=f"migrated:{source}")
        written.append((ccat, ckey, val))

    for summary, ts in sessions:
        store.save_session_summary(summary)
    print(f"Copied {len(sessions)} session summaries.")

    print("\n" + "=" * 60)
    print(f"DONE — {len(written)} facts written, {len(dropped)} dropped, "
          f"{len(sessions)} sessions copied.")
    print("=" * 60)
    print("\nFinal facts in new store:")
    for f in store.list_all():
        print(f"  [{f['category']}] {f['key']} = {f['value']!r}  (source={f['source']})")
    print(f"\nOld DBs NOT touched — {ROOT_DB} and {LONGTERM_DB} still exist.")
    print("Once you've checked the list above looks right, delete them yourself.")


if __name__ == "__main__":
    migrate()