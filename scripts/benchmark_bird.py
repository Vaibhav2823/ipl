# File: E:\ipl\scripts\benchmark_bird.py
import json
import sqlite3
import os
import time
import argparse
import sys
from openai import OpenAI
from anthropic import Anthropic

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
BIRD_DIR = os.path.join(ROOT_DIR, "bird")
INPUT_FILE = os.path.join(BIRD_DIR, "dev.json")
DB_ROOT_DIR = os.path.join(BIRD_DIR, "dev_databases")
OUTPUT_DIR = os.path.join(ROOT_DIR, "benchmarks_bird")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

def get_schema_inline(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        conn.close()
        return "\n".join([t[0] for t in tables if t[0]])
    except Exception as e:
        return f"Error reading schema: {str(e)}"

def call_model(provider, client, model, system_prompt, user_prompt):
    try:
        # Set a strict timeout (e.g., 45 seconds) to prevent hanging forever
        if provider in ["openai", "openrouter"]:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                timeout=45  # <-- Anti-freeze timeout
            )
            return response.choices[0].message.content
        elif provider == "anthropic":
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0,
                timeout=45
            )
            return response.content[0].text
    except Exception as e:
        return f"API_ERROR: {str(e)}"

def run_benchmark(provider, model_name, api_key, limit=None):
    safe_name = model_name.replace("/", "_").replace(":", "")
    outfile = os.path.join(OUTPUT_DIR, f"bird_results_{safe_name}.json")
    
    print(f"\n--- Starting BIRD Benchmark (Resumable): {model_name} ---")

    # --- RESUME LOGIC ---
    results = []
    start_index = 0
    if os.path.exists(outfile):
        try:
            with open(outfile, 'r', encoding='utf-8') as f:
                results = json.load(f)
                start_index = len(results)
                print(f"🔄 Resuming from item {start_index}...")
        except json.JSONDecodeError:
            print("⚠️ Output file corrupted. Starting fresh.")

    # Initialize Client
    client = None
    if provider == "openai": client = OpenAI(api_key=api_key)
    elif provider == "anthropic": client = Anthropic(api_key=api_key)
    elif provider == "openrouter": client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: Could not find {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        full_dataset = json.load(f)

    # Limit logic
    if limit:
        dataset_to_process = full_dataset[start_index:limit]
    else:
        dataset_to_process = full_dataset[start_index:]

    if not dataset_to_process:
        print("✅ All items already processed!")
        return

    print(f"Processing {len(dataset_to_process)} remaining items...")

    for i, item in enumerate(dataset_to_process):
        abs_index = start_index + i
        db_id = item['db_id']
        question = item['question']
        evidence = item.get('evidence', '') 
        
        db_path = os.path.join(DB_ROOT_DIR, db_id, f"{db_id}.sqlite")
        schema_text = get_schema_inline(db_path)
        
        system_prompt = "You are an expert SQL data analyst. Output only valid SQLite SQL queries. No markdown, no explanations."
        user_prompt = f"Given the following database schema:\n{schema_text}\n\nExternal Knowledge: {evidence}\n\nQuestion: {question}\n\nWrite a SQL query to answer the question."

        start_time = time.time()
        generated_sql = call_model(provider, client, model_name, system_prompt, user_prompt)
        duration = time.time() - start_time
        
        clean_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
        
        # Execute Check
        exec_success = False
        exec_result = None
        try:
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(clean_sql)
                exec_result = cursor.fetchall()
                conn.close()
                exec_success = True
            else:
                exec_result = "DB_FILE_NOT_FOUND"
        except Exception as e:
            exec_result = str(e)

        status_icon = "[OK]" if exec_success else "[FAIL]"
        print(f"[{abs_index+1}/{len(full_dataset)}] {db_id} ({round(duration, 1)}s) - {status_icon}")

        results.append({
            "id": abs_index,
            "db_id": db_id,
            "question": question,
            "gold_sql": item['SQL'],
            "generated_sql": clean_sql,
            "execution_result": str(exec_result)[:200], # Truncate large results
            "execution_success": exec_success,
            "time_taken": duration
        })
        
        # --- AUTO-SAVE EVERY 5 ITEMS ---
        if (i + 1) % 5 == 0:
            with open(outfile, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=4)

    # Final Save
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
    
    print(f"\n✅ Benchmark Complete! Saved to: {outfile}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", type=str, required=True)
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    key = ""
    if args.provider == "openai": key = OPENAI_API_KEY
    elif args.provider == "anthropic": key = ANTHROPIC_API_KEY
    elif args.provider == "openrouter": key = OPENROUTER_API_KEY

    run_benchmark(args.provider, args.model, key, args.limit)