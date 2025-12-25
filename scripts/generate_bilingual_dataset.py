# File: E:\ipl\scripts\generate_bilingual_dataset.py
import json
import sqlite3
import os

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# Paths
INPUT_FILE = os.path.join(ROOT_DIR, "gold_dataset_hindi_cleaned.json")
OUTPUT_FILE = os.path.join(ROOT_DIR, "gold_dataset_bilingual.json")
DB_PATH = os.path.join(ROOT_DIR, 'data', 'processed', 'ipl.db')

def generate_dataset():
    print(f"--- 🚀 Generating Bilingual Dataset with Column Metadata ---")
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: Input dataset not found at {INPUT_FILE}")
        return

    try:
        # Connect to DB
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Load Data
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        success_count = 0
        
        # Process each entry
        for i, item in enumerate(data):
            sql = item.get('query')
            
            if sql:
                try:
                    # Execute SQL just to get metadata (LIMIT 1 is enough for headers)
                    # We use the original query but we technically only need description
                    cursor.execute(sql)
                    
                    # Extract Column Names (in order)
                    # cursor.description returns a tuple (name, type_code, ...)
                    col_names = [desc[0] for desc in cursor.description]
                    
                    # Add to item
                    item['column_names'] = col_names
                    
                    # Update status
                    success_count += 1
                    
                except sqlite3.Error as e:
                    print(f"⚠️ Query Error at Item #{i+1}: {e}")
                    # If execution fails, we set an empty list or leave it out
                    item['column_names'] = []
            else:
                item['column_names'] = []

        conn.close()

        # Save Final File
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            # ensure_ascii=False preserves Hindi characters
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print(f"\n✅ Success! Processed {len(data)} items.")
        print(f"   Queries successfully executed: {success_count}")
        print(f"   Saved to: {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    generate_dataset()