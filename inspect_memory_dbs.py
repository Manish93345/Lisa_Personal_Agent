"""
inspect_memory_dbs.py — Phase 2, Step 2.1

Dumps both existing lisa_memory.db files so we can see REAL data
before designing the Phase 2 consolidated store. Read-only — doesn't
change anything. Run from your project root:

    python inspect_memory_dbs.py
"""
import sqlite3
from pathlib import Path

ROOT_DB = Path("lisa_memory.db")
LONGTERM_DB = Path("data/memory/lisa_memory.db")


def dump_root_db():
    print("=" * 60)
    print(f"ROOT DB — {ROOT_DB.resolve()}")
    print("=" * 60)
    if not ROOT_DB.exists():
        print("  (file does not exist)")
        return set()
    conn = sqlite3.connect(ROOT_DB)
    rows = conn.execute(
        "SELECT key, value, category, last_updated, expires_at FROM memories"
    ).fetchall()
    conn.close()
    print(f"  {len(rows)} rows in 'memories' table\n")
    for key, value, category, last_updated, expires_at in rows:
        exp = f" (expires {expires_at})" if expires_at else ""
        print(f"  [{category or '-'}] {key} = {value!r}{exp}")
    print()
    return {r[0] for r in rows}   # set of keys


def dump_longterm_db():
    print("=" * 60)
    print(f"data/memory DB — {LONGTERM_DB.resolve()}")
    print("=" * 60)
    if not LONGTERM_DB.exists():
        print("  (file does not exist)")
        return set()
    conn = sqlite3.connect(LONGTERM_DB)
    rows = conn.execute(
        "SELECT category, key, value, timestamp FROM memories ORDER BY category"
    ).fetchall()
    sums = conn.execute(
        "SELECT summary, timestamp FROM sessions ORDER BY id DESC"
    ).fetchall()
    conn.close()
    print(f"  {len(rows)} rows in 'memories' table")
    print(f"  {len(sums)} rows in 'sessions' table\n")
    for category, key, value, timestamp in rows:
        print(f"  [{category}] {key} = {value!r}  ({timestamp[:10]})")
    if sums:
        print("\n  -- session summaries --")
        for summary, timestamp in sums:
            print(f"  [{timestamp[:10]}] {summary[:100]}")
    print()
    return {r[1] for r in rows}   # set of keys


if __name__ == "__main__":
    root_keys = dump_root_db()
    longterm_keys = dump_longterm_db()

    overlap = root_keys & longterm_keys
    print("=" * 60)
    print("OVERLAP CHECK")
    print("=" * 60)
    if overlap:
        print(f"  {len(overlap)} key name(s) appear in BOTH dbs: {sorted(overlap)}")
        print("  (worth checking manually if values agree or conflict)")
    else:
        print("  No overlapping key names between the two stores.")