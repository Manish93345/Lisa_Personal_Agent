import os
import sqlite3
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# In folders ko hum hamesha skip karenge taaki scan lightning fast rahe aur system hang na ho
IGNORED_DIRS = {
    'node_modules', '.git', '__pycache__', 'venv', 'env', 
    'build', 'dist', '.idea', '.vscode', 'lisajaanu', 'lisajaan'
}

class FileDatabase:
    def __init__(self, db_path="lisa_files.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_index (
                path TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                extension TEXT,
                folder_path TEXT
            )
        ''')
        self.conn.commit()

    def add_or_update_file(self, path):
        filename = os.path.basename(path)
        folder_path = os.path.dirname(path)
        extension = os.path.splitext(filename)[1].lower()
        
        try:
            self.cursor.execute('''
                INSERT INTO file_index (path, filename, extension, folder_path)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO NOTHING
            ''', (path, filename, extension, folder_path))
            self.conn.commit()
        except Exception as e:
            pass # Ignore minor file lock errors

    def remove_file(self, path):
        self.cursor.execute('DELETE FROM file_index WHERE path = ?', (path,))
        self.conn.commit()

    def search(self, query):
        """Lisa ke use ke liye search function"""
        self.cursor.execute('''
            SELECT path FROM file_index 
            WHERE filename LIKE ? LIMIT 10
        ''', (f'%{query}%',))
        return [row[0] for row in self.cursor.fetchall()]

# ── Watchdog Event Handler ──
class RealTimeSyncHandler(FileSystemEventHandler):
    def __init__(self, db: FileDatabase):
        self.db = db

    def on_created(self, event):
        if not event.is_directory:
            # Check if it's inside an ignored dir
            if not any(ignored in event.src_path for ignored in IGNORED_DIRS):
                self.db.add_or_update_file(event.src_path)
                # print(f"[File Added] {os.path.basename(event.src_path)}")

    def on_deleted(self, event):
        if not event.is_directory:
            self.db.remove_file(event.src_path)
            # print(f"[File Removed] {os.path.basename(event.src_path)}")

    def on_moved(self, event):
        if not event.is_directory:
            self.db.remove_file(event.src_path)
            if not any(ignored in event.dest_path for ignored in IGNORED_DIRS):
                self.db.add_or_update_file(event.dest_path)

# ── Main Scanner Manager ──
class FileIndexer:
    def __init__(self, target_directories):
        self.targets = target_directories
        self.db = FileDatabase()
        self.observer = Observer()

    def initial_scan(self):
        print("\n  [Indexer] Initial scan start kar rahi hoon... system hang nahi hoga! 🚀")
        count = 0
        for target in self.targets:
            if not os.path.exists(target):
                continue
                
            for root, dirs, files in os.walk(target):
                # SMART PRUNING: Ye loop un directories ko nikal dega jinhe scan nahi karna
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                
                for file in files:
                    filepath = os.path.join(root, file)
                    self.db.add_or_update_file(filepath)
                    count += 1
                    
        print(f"  [Indexer] Done! Total {count} files database mein map ho gayi hain. ✅")

    def start_realtime_watch(self):
        handler = RealTimeSyncHandler(self.db)
        for target in self.targets:
            if os.path.exists(target):
                self.observer.schedule(handler, target, recursive=True)
        self.observer.start()
        print("  [Indexer] Real-time file watcher background mein chalu hai 👀")

    def stop(self):
        self.observer.stop()
        self.observer.join()

# ── Quick Test ──
if __name__ == "__main__":
    # Tumhari D drive ya project folder yahan daal sakte ho
    directories_to_watch = [r"D:\LISA_AGENT"] 
    
    indexer = FileIndexer(directories_to_watch)
    
    # 1. Pehle pura folder scan karegi (Fast os.walk skip logic ke sath)
    indexer.initial_scan()
    
    # 2. Phir live monitor karegi
    indexer.start_realtime_watch()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        indexer.stop()