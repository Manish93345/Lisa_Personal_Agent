"""
LISA — Smart File Finder & Indexer (Unified Blueprint)
======================================================
1. Background Indexer: Scans C: (User folders) + D: and creates lisa_files.db
2. Fuzzy Searcher: Reads from DB, uses RapidFuzz, returns exact path instantly.
"""

import os
import sqlite3
import re
import threading
from pathlib import Path
from rapidfuzz import fuzz, process

DB_PATH = "lisa_files.db"

# 🚨 In folders ko humesha ignore kiya jayega (Lightning Fast Scan)
SKIP_FOLDERS = {
    "__pycache__", ".git", ".venv", "node_modules", ".idea",
    "venv", "env", ".vs", ".vscode", "$RECYCLE.BIN",
    "System Volume Information", ".Trash-1000", "AppData", "Windows", "Program Files"
}

def _get_search_roots():
    """Sirf User Folders aur D: Drive return karega"""
    home = Path.home()
    roots = [
        str(home / "Desktop"),
        str(home / "Downloads"),
        str(home / "Documents"),
        str(home / "Videos"),
        str(home / "Pictures"),
        str(home / "Music"),
    ]
    if os.path.exists("D:\\"):
        roots.append("D:\\")
    return roots

# ── 1. The Indexer (Runs in Background) ──────────────────────────────

def build_index():
    """Scans folders and builds the SQLite index silently."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Table structure
        cursor.execute('''CREATE TABLE IF NOT EXISTS file_index 
                          (id INTEGER PRIMARY KEY, name TEXT, path TEXT, is_dir INTEGER)''')
        cursor.execute('DELETE FROM file_index') # Clear old data for fresh index
        
        search_roots = _get_search_roots()
        batch_data = []
        count = 0
        
        for root_dir in search_roots:
            if not os.path.exists(root_dir):
                continue

            for root, dirs, files in os.walk(root_dir):
                # 🚨 Pruning: Drop unwanted folders IN-PLACE so os.walk ignores them
                dirs[:] = [d for d in dirs if d not in SKIP_FOLDERS and not d.startswith(".")]

                # Add Folders
                for d in dirs:
                    batch_data.append((d.lower(), os.path.join(root, d), 1))
                
                # Add Files
                for f in files:
                    batch_data.append((f.lower(), os.path.join(root, f), 0))

                # Batch insert (Memory efficient)
                if len(batch_data) > 10000:
                    cursor.executemany('INSERT INTO file_index (name, path, is_dir) VALUES (?, ?, ?)', batch_data)
                    count += len(batch_data)
                    batch_data = []

        # Insert remaining
        if batch_data:
            cursor.executemany('INSERT INTO file_index (name, path, is_dir) VALUES (?, ?, ?)', batch_data)
            count += len(batch_data)
            
        conn.commit()
        print(f"  [Indexer] System mapped successfully. Indexed {count} items.")
    except Exception as e:
        print(f"  [Indexer] Error: {e}")
    finally:
        conn.close()

def run_indexer_background():
    """Starts the indexer in a background thread."""
    t = threading.Thread(target=build_index, daemon=True)
    t.start()


# ── 2. The Searcher (For Chat Commands) ──────────────────────────────

def _clean_hint(hint: str) -> str:
    """Removes useless words like 'movie', 'file' so fuzzy logic doesn't get confused."""
    hint = hint.lower().strip()
    hint = re.sub(r'\b(photo|image|file|pdf|doc|video|pic|picture|screenshot|ss|movie|song)\b', '', hint).strip()
    return hint

def smart_find(folder_hint: str = "", file_hint: str = "") -> tuple[bool, str, str]:
    """Loads data from SQLite and uses RapidFuzz to find the exact file/folder."""
    if not os.path.exists(DB_PATH):
        return False, "", "File index abhi ban raha hai, bas ek minute dijiye."

    folder_hint = _clean_hint(folder_hint)
    file_hint = _clean_hint(file_hint)

    if not folder_hint and not file_hint:
        return False, "", "Kya dhundhna hai bata do."

    target_hint = file_hint if file_hint else folder_hint
    is_dir_flag = 0 if file_hint else 1

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Load all names and paths into RAM for Lightning Fast Fuzzing
        cursor.execute('SELECT name, path FROM file_index WHERE is_dir = ?', (is_dir_flag,))
        targets = cursor.fetchall()
        
        if not targets:
            return False, "", "System mein koi files nahi mili."

        names = [t[0] for t in targets]

        # 🚨 Magic: RapidFuzz ignores spaces, spelling mistakes, and extensions
        result = process.extractOne(
            target_hint,
            names,
            scorer=fuzz.token_set_ratio,
            score_cutoff=55  # Minimum 55% match required
        )

        if result:
            matched_name, score, idx = result
            matched_path = targets[idx][1]
            item_type = "File" if file_hint else "Folder"
            
            print(f"  [FileFinder] Match: '{target_hint}' -> '{Path(matched_path).name}' (score: {score})")
            return True, matched_path, f"Mil gayi: {Path(matched_path).name}"
        else:
            return False, "", f"'{target_hint}' jaisa kuch nahi mila laptop mein."

    except Exception as e:
        return False, "", f"Search error: {e}"
    finally:
        conn.close()

if __name__ == "__main__":
    # Test script if you run this file directly
    print("Testing Indexer...")
    build_index()
    success, path, msg = smart_find(file_hint="deadpool 2")
    print(f"Result: {success} | {msg} | {path}")