# File: E:\ipl\scripts\generate_bilingual_dataset_llm.py
import json
import sqlite3
import os
import time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# --- CONFIGURATION ---
# Ensure GOOGLE_API_KEY is set in your environment variables
# os.environ["GOOGLE_API_KEY"] = "YOUR_KEY_HERE" 

# Determine paths based on the script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # E:\ipl\scripts
ROOT_DIR = os.path.dirname(BASE_DIR)                  # E:\ipl

# Input: The original cleaned dataset
INPUT_FILE = os.path.join(ROOT_DIR, "gold_dataset_hindi_cleaned.json")
# Output: The new bilingual dataset with intuitive column names
OUTPUT_FILE = os.path.join(ROOT_DIR, "gold_dataset_bilingual.json")
# Database Path
DB_PATH = os.path.join(ROOT_DIR, 'data', 'processed', 'ipl.db')

# --- MODEL CONFIGURATION ---
# CHANGED: 'gemini-1.5-flash' is retired. Using 'gemini-2.5-flash'.
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0,
    max_retries=3
)

# --- PROMPT TEMPLATE ---
header_cleaning_prompt = ChatPromptTemplate.from_template(
    """
    You are a Data Analyst. I will give you a SQL query and the "Raw Column Headers" returned by the database.
    Your task is to generate **intuitive, human-readable column names** for the final output.

    **Input Context:**
    SQL Query: {query}
    Raw Headers: {raw_headers}

    **Rules:**
    1. Keep the **exact same order** of columns.
    2. Make names concise but descriptive (e.g., change `SUM(runs)` to `Total Runs`, `t2.player_name` to `Player Name`).
    3. If a column is already intuitive (like `season`), keep it as is or capitalize it (e.g., `Season`).
    4. Return **ONLY** a valid JSON list of strings. Do not output markdown or explanations.

    **Example Output:**
    ["Player Name", "Total Runs", "Strike Rate"]
    """
)

chain = header_cleaning_prompt | llm

def get_raw_headers(cursor, sql):
    """Executes SQL to get the raw, technical column names from the DB."""
    try:
        # Execute logic to get metadata only (limit 0 avoids fetching data)
        try:
            cursor.execute(f"SELECT * FROM ({sql}) LIMIT 0")
        except:
            cursor.execute(sql) # Fallback to normal execution
            
        return [desc[0] for desc in cursor.description]
    except Exception as e:
        return None

def generate_dataset():
    print(f"--- 🚀 Generating Bilingual Dataset (Gemini Powered) ---")
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: Input file not found at {INPUT_FILE}")
        return

    # Connect to DB
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Load Input
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    processed_count = 0
    success_count = 0

    print(f"Processing {len(data)} items...")

    for i, item in enumerate(data):
        sql = item.get('query')
        if not sql:
            item['column_names'] = []
            continue

        # 1. Get Raw Headers from DB (Ground Truth)
        raw_headers = get_raw_headers(cursor, sql)
        
        if raw_headers:
            try:
                # 2. Ask Gemini to prettify them
                response = chain.invoke({
                    "query": sql, 
                    "raw_headers": str(raw_headers)
                })
                
                # Clean up response
                clean_response = response.content.strip().replace("```json", "").replace("```", "")
                intuitive_headers = json.loads(clean_response)
                
                # Safety Check: Ensure length matches
                if len(intuitive_headers) == len(raw_headers):
                    item['column_names'] = intuitive_headers
                    success_count += 1
                else:
                    print(f"\n⚠️ Item {i+1}: Column count mismatch. Using raw headers.")
                    item['column_names'] = raw_headers
                    
            except Exception as e:
                print(f"\n⚠️ LLM/Parse Error on item {i+1}: {e}")
                item['column_names'] = raw_headers # Fallback
        else:
            item['column_names'] = []
            print(f"\n⚠️ SQL Execution failed for item {i+1}")

        processed_count += 1
        print(f"   > Processed: {processed_count}/{len(data)}", end="\r")
        
        # Sleep 4 seconds to stay safe within free tier limits
        time.sleep(4) 

    conn.close()

    # Save Final File
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"\n\n✅ Success! Generated {OUTPUT_FILE}")
    print(f"   Total Items: {processed_count}")
    print(f"   LLM Enhanced: {success_count}")

if __name__ == "__main__":
    generate_dataset()