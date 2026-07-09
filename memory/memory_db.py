import sqlite3
from datetime import datetime

class MemoryManager:
    def __init__(self, db_path="lisa_memory.db"):
        # Connect to SQLite DB (creates file if it doesn't exist)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        # Create table with a UNIQUE key to prevent duplicates
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        self.conn.commit()

    def upsert_memory(self, key, value, category="general", expires_at=None):
        """
        ADD ya UPDATE dono ka kaam yahi karega. 
        Agar key exist karti hai toh update karega, nahi toh naya add karega.
        """
        query = '''
            INSERT INTO memories (key, value, category, last_updated, expires_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                last_updated = CURRENT_TIMESTAMP,
                expires_at = excluded.expires_at
        '''
        self.cursor.execute(query, (key, value, category, expires_at))
        self.conn.commit()
        print(f"[Memory DB] Upserted: {key} -> {value}")

    def delete_memory(self, key):
        """Memory delete karne ke liye"""
        self.cursor.execute('DELETE FROM memories WHERE key = ?', (key,))
        self.conn.commit()
        print(f"[Memory DB] Deleted: {key}")

    def cleanup_expired(self):
        """Background task ke liye jo expired memories hatayega"""
        current_time = datetime.now().isoformat()
        self.cursor.execute('''
            DELETE FROM memories 
            WHERE expires_at IS NOT NULL AND expires_at < ?
        ''', (current_time,))
        deleted_count = self.cursor.rowcount
        self.conn.commit()
        if deleted_count > 0:
            print(f"[Memory DB] Cleaned up {deleted_count} expired memories.")

    def get_all_active_memories(self):
        """Chat session mein context inject karne ke liye"""
        self.cleanup_expired() # Pehle kachra saaf karo
        self.cursor.execute('SELECT key, value, category FROM memories')
        rows = self.cursor.fetchall()
        
        # Format for LLM prompt
        formatted_memories = []
        for row in rows:
            formatted_memories.append({"key": row[0], "value": row[1], "category": row[2]})
        return formatted_memories

    def close(self):
        self.conn.close()

# Quick Test
if __name__ == "__main__":
    db = MemoryManager()
    
    # User says: "I am in 6th sem"
    db.upsert_memory("current_semester", "6th Sem", "education")
    
    # User says later: "I passed 6th sem, I am in 7th now"
    # Ye naya fact purane ko replace kar dega because 'key' same hai!
    db.upsert_memory("current_semester", "7th Sem", "education")
    
    # Temporary reminder
    # Format: YYYY-MM-DDTHH:MM:SS
    db.upsert_memory("meeting_reminder", "Meeting with team at 5 PM", "event", "2026-06-25T17:00:00")
    
    print("\nActive Memories:")
    for mem in db.get_all_active_memories():
        print(mem)