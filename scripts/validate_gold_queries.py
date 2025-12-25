# File: E:\ipl\scripts\validate_gold_queries.py
import json
import sqlite3
import os

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# Paths
INPUT_JSON_PATH = os.path.join(ROOT_DIR, "gold_dataset_hindi_cleaned.json")
DB_PATH = os.path.join(ROOT_DIR, 'data', 'processed', 'ipl.db')
OUTPUT_LOG_PATH = os.path.join(ROOT_DIR, "gold_query_validation_log.txt")

def validate_queries():
    print(f"--- 🚀 Starting Gold Query Validation ---")
    
    # 1. Verify Database Exists
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    # 2. Connect to Database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
    except Exception as e:
        print(f"❌ Error connecting to DB: {e}")
        return

    # 3. Load Input Dataset
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"❌ Error: Input dataset not found at {INPUT_JSON_PATH}")
        return

    try:
        with open(INPUT_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error decoding JSON: {e}")
        return

    # 4. Open Log File for Writing
    with open(OUTPUT_LOG_PATH, 'w', encoding='utf-8') as log_file:
        
        success_count = 0
        error_count = 0
        
        for i, item in enumerate(data):
            query_number = i + 1
            sql = item.get('query')
            question = item.get('question_english') or item.get('question')
            
            log_file.write(f"--- Entry #{query_number} ---\n")
            log_file.write(f"Question: {question}\n")
            log_file.write(f"SQL: {sql}\n")
            
            if not sql:
                log_file.write("Result: [SKIPPED] No SQL query found in JSON entry.\n\n")
                error_count += 1
                continue

            try:
                # Execute the SQL
                cursor.execute(sql)
                result = cursor.fetchall()
                
                # Write SUCCESS output
                log_file.write(f"Result: [SUCCESS]\n{result}\n\n")
                success_count += 1
                
            except sqlite3.Error as e:
                # Write ERROR output
                log_file.write(f"Result: [ERROR]\n{e}\n\n")
                error_count += 1

    conn.close()
    
    print(f"\n✅ Validation Complete.")
    print(f"   Total Queries Processed: {len(data)}")
    print(f"   Successful: {success_count}")
    print(f"   Errors: {error_count}")
    print(f"   Log saved to: {OUTPUT_LOG_PATH}")

if __name__ == "__main__":
    validate_queries()