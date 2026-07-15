import sqlite3
import os

def search_local_file(query: str):
    """
    Lisa ke liye local database se file search karta hai.
    """
    db_path = "lisa_files.db"
    
    # Agar database exist nahi karta
    if not os.path.exists(db_path):
        return False, "SYSTEM_RESULT|find_file|Database nahi mila. File indexer run nahi hua hai."

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Smart Search: Filename ya path dono mein dhundhega
        cursor.execute('''
            SELECT filename, path FROM file_index 
            WHERE filename LIKE ? OR path LIKE ? 
            LIMIT 5
        ''', (f'%{query}%', f'%{query}%'))
        
        results = cursor.fetchall()
        conn.close()

        if not results:
            return True, f"SYSTEM_RESULT|find_file|'{query}' naam ki koi file nahi mili."

        # Results ko string mein format karna (Agent.py ke liye)
        formatted_results = []
        for filename, path in results:
            formatted_results.append(f"Name: {filename} (Path: {path})")
            
        final_data = ";;".join(formatted_results)
        return True, f"SYSTEM_RESULT|find_file|{final_data}"

    except Exception as e:
        return False, f"File search mein error aayi: {str(e)}"