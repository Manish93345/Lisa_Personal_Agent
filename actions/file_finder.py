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
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm"}

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

def resolve_target_file(matched_path: str, user_query: str) -> tuple[str, str]:
    """
    Agar matched_path ek Folder hai aur user video chalane ko bol raha hai,
    toh ye function folder ke andar se sabse relevant video path nikal ke dega.
    """
    if not os.path.exists(matched_path):
        return matched_path, "path_not_found"

    # Agar match direct ek Video File hai
    if os.path.isfile(matched_path):
        return matched_path, "file"

    # Agar match ek Folder hai:
    if os.path.isdir(matched_path):
        query_lower = user_query.lower()
        video_requested = any(w in query_lower for w in ["video", "chala", "play", "movie", "clip", "gaana", "song"])

        if video_requested:
            found_videos = []
            # Folder aur Sub-folders scan karo
            for root, dirs, files in os.walk(matched_path):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in VIDEO_EXTENSIONS:
                        found_videos.append(os.path.join(root, file))

            if found_videos:
                # Video mil gayi! (Pehli ya latest video pick kar sakte hain)
                selected_video = found_videos[0]
                print(f"  [FileFinder] Folder '{os.path.basename(matched_path)}' ke andar se video mili: {os.path.basename(selected_video)}")
                return selected_video, "video_from_folder"

        # Agar video request nahi thi ya video file nahi mili, toh Folder hi open hoga
        return matched_path, "folder"

    return matched_path, "unknown"

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
    """Removes useless chatty words so fuzzy logic isolates the real file name."""
    import re
    hint = hint.lower().strip()
    
    # 🚨 FIX: Massive list of Hindi/Hinglish chat stopwords added
    stopwords = r'\b(lisa|suno|jara|photo|images?|files?|pdf|docs?|videos?|pics?|pictures?|screenshots?|ss|movies?|songs?|meri|mera|mere|ki|ka|ke|kaha|kahan|par|padi|hain|hai|ek|chala|do|play|karo|folder|laptop|mein|batana|or|koi|bhi|achhi|si|usme|se|dhoondho|kholo|open|karde|karna|dikhao)\b'
    
    hint = re.sub(stopwords, '', hint)
    hint = hint.replace('_', ' ').strip()
    return re.sub(r'\s+', ' ', hint).strip()

def smart_find(folder_hint: str = "", file_hint: str = "", raw_query: str = "", return_score: bool = False):
    """Loads data from SQLite, does SPACELESS exact matching, and dynamically resolves ANY file type."""
    import os
    import sqlite3
    import re
    
    if not os.path.exists(DB_PATH):
        err = "File index abhi ban raha hai, bas ek minute dijiye."
        return (False, "", err, 0) if return_score else (False, "", err)

    # 🚨 MEGA STOPWORD CLEANER: Tumhare sentence ka sara kachra hata dega
    query_to_clean = (file_hint or folder_hint or raw_query).lower()
    
    stopwords = r'\b(lisa|suno|jara|photo|images?|files?|pdf|docs?|videos?|pics?|pictures?|screenshots?|ss|movies?|songs?|meri|mera|mere|ki|ka|ke|kaha|kahan|par|padi|hain|hai|ek|chala|do|play|karo|folder|laptop|mein|batana|or|aur|koi|bhi|achhi|si|usme|se|dhoondho|kholo|open|karde|karna|dikhao|dena|kar|mujhe|dikha|bata|ya|kuch|iska)\b'
    
    clean_q = re.sub(stopwords, ' ', query_to_clean)
    clean_q = re.sub(r'[^\w\s]', ' ', clean_q) # Remove punctuations
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    
    if not clean_q:
        err = "Kya dhundhna hai clear nahi hua."
        return (False, "", err, 0) if return_score else (False, "", err)

    # 🚨 UNIVERSAL RESOLVER: Samajhna ki usko kya media chahiye
    target_exts = set()
    if any(w in query_to_clean for w in ["video", "movie", "play", "chala"]):
        target_exts.update({".mp4", ".mkv", ".avi", ".mov", ".webm"})
    if any(w in query_to_clean for w in ["song", "gaana", "audio", "music", "baja"]):
        target_exts.update({".mp3", ".wav", ".flac", ".m4a"})
    if any(w in query_to_clean for w in ["photo", "pic", "image", "screenshot"]):
        target_exts.update({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
    if any(w in query_to_clean for w in ["doc", "pdf", "resume", "file", "word", "excel"]):
        target_exts.update({".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt"})
    if any(w in query_to_clean for w in ["code", "script", "python"]):
        target_exts.update({".py", ".js", ".html", ".css", ".cpp", ".java"})

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Load ALL Files and Folders (is_dir filter hat gaya)
        cursor.execute('SELECT name, path, is_dir FROM file_index')
        targets = cursor.fetchall()
        
        if not targets:
            err = "System mein koi files nahi mili."
            return (False, "", err, 0) if return_score else (False, "", err)

        # 🚨 THE MAGIC FIX: SPACELESS SUBSTRING MATCHING
        # "free fire" -> "freefire". Ab ye "free_fire", "Free Fire", "FreeFire" sabko pakad lega!
        search_term = clean_q.replace(" ", "")
        
        matched_items = []
        for t in targets:
            # Database ki file ka bhi space aur underscore hata do
            db_name = t[0].lower().replace(" ", "").replace("_", "")
            if search_term in db_name:
                matched_items.append(t)
                
        best_match = None
        score = 100 # Agar substring mil gaya toh confidence 100%
        
        if matched_items:
            # Agar multiple mile, toh FOLDER ko priority do (taaki hum uske andar video dhundh sake)
            dirs = [t for t in matched_items if t[2] == 1]
            files = [t for t in matched_items if t[2] == 0]
            
            if dirs:
                # Sabse chota naam pick karo (wohi exact folder hoga)
                best_match = min(dirs, key=lambda x: len(x[0]))
            else:
                best_match = min(files, key=lambda x: len(x[0]))
        else:
            # Agar spaceless matching bhi fail ho (jaise spelling mistake), TABHI RapidFuzz use karo
            from rapidfuzz import fuzz, process
            names = [t[0] for t in targets]
            results = process.extract(clean_q, names, scorer=fuzz.token_set_ratio, limit=3, score_cutoff=70)
            if results:
                idx = results[0][2]
                best_match = targets[idx]
                score = results[0][1]

        if best_match:
            matched_name = best_match[0]
            matched_path = best_match[1]
            is_dir = best_match[2]
            
            final_path = matched_path
            extra_msg = ""

            # 🚨 SMART MEDIA RESOLVER (Automatically pick video from inside folder)
            if is_dir == 1 and target_exts:
                found_file = None
                for root, dirs, local_files in os.walk(matched_path):
                    for f in local_files:
                        if os.path.splitext(f)[1].lower() in target_exts:
                            found_file = os.path.join(root, f)
                            break
                    if found_file: 
                        break
                
                if found_file:
                    final_path = found_file
                    extra_msg = f" (Folder '{matched_name}' ke andar se automatically media open kiya)"

            msg = f"Exact path mil gaya: {final_path}{extra_msg}"
            return (True, final_path, msg, score) if return_score else (True, final_path, msg)
        else:
            err = f"'{clean_q}' jaisa kuch nahi mila laptop mein."
            return (False, "", err, 0) if return_score else (False, "", err)

    except Exception as e:
        err = f"Search error: {e}"
        return (False, "", err, 0) if return_score else (False, "", err)
    finally:
        conn.close()
        

if __name__ == "__main__":
    # Test script if you run this file directly
    print("Testing Indexer...")
    build_index()
    success, path, msg = smart_find(file_hint="deadpool 2")
    print(f"Result: {success} | {msg} | {path}")