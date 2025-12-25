import json
import sqlite3
import os
import time
import glob
import re
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
DB_ROOT_DIR = os.path.join(BIRD_DIR, "dev_databases")
BENCHMARKS_DIR = os.path.join(ROOT_DIR, "benchmarks_bird")

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

def get_schema_inline(db_path):
    """Extracts schema for the prompt."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        conn.close()
        return "\n".join([t[0] for t in tables if t[0]])
    except Exception as e:
        return f"Error reading schema: {str(e)}"

def determine_provider_model(filename):
    """Infers provider and model name from the filename."""
    name = os.path.basename(filename).replace("bird_results_", "").replace(".json", "")
    
    # Reconstruct model name (reversing the safe_name logic)
    # This is a heuristic; adjust if your filenames are complex
    if "gpt" in name:
        return "openai", "gpt-4o" # Assuming gpt-4o based on your previous runs
    elif "claude" in name:
        # Try to reconstruct common Claude IDs
        if "sonnet" in name: return "anthropic", "claude-3-7-sonnet-latest"
        return "anthropic", "claude-3-5-sonnet-20240620"
    else:
        # OpenRouter models (Llama, Qwen, Gemma, DeepSeek)
        # We need to map back to the exact OpenRouter ID
        if "llama" in name: return "openrouter", "meta-llama/llama-3.1-8b-instruct"
        if "qwen" in name: return "openrouter", "qwen/qwen-2.5-7b-instruct"
        if "gemma" in name: return "openrouter", "google/gemma-2-9b-it"
        if "deepseek" in name: return "openrouter", "deepseek/deepseek-r1"
        
    return None, None

def call_model(provider, client, model, system_prompt, user_prompt):
    """Calls the API with a strict 45s timeout."""
    try:
        if provider in ["openai", "openrouter"]:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                timeout=45  # STRICT TIMEOUT
            )
            return response.choices[0].message.content
        elif provider == "anthropic":
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0,
                timeout=45 # STRICT TIMEOUT
            )
            return response.content[0].text
    except Exception as e:
        return f"API_ERROR: {str(e)}"

def repair_file(filepath):
    print(f"\n--- 🛠️  Checking: {os.path.basename(filepath)} ---")
    
    provider, model_name = determine_provider_model(filepath)
    if not provider:
        print(f"⚠️  Could not identify model from filename. Skipping.")
        return

    print(f"   > Detected: {provider} / {model_name}")
    
    # Init Client
    client = None
    if provider == "openai": client = OpenAI(api_key=OPENAI_API_KEY)
    elif provider == "anthropic": client = Anthropic(api_key=ANTHROPIC_API_KEY)
    elif provider == "openrouter": client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    repaired_count = 0
    indices_to_repair = []

    # 1. Identify broken entries
    for i, item in enumerate(data):
        sql = item.get('generated_sql', '')
        if "API_ERROR" in sql or not sql.strip() or "timeout" in sql.lower():
            indices_to_repair.append(i)

    if not indices_to_repair:
        print("   ✅ File is clean! No errors found.")
        return

    print(f"   found {len(indices_to_repair)} items to repair.")

    # 2. Repair Loop
    for idx in indices_to_repair:
        item = data[idx]
        db_id = item['db_id']
        question = item['question']
        evidence = item.get('evidence', '')
        
        print(f"   [Reparing #{idx}] {db_id}...", end="\r")
        
        db_path = os.path.join(DB_ROOT_DIR, db_id, f"{db_id}.sqlite")
        schema_text = get_schema_inline(db_path)
        
        system_prompt = "You are an expert SQL data analyst. Output only valid SQLite SQL queries. No markdown."
        user_prompt = f"Given the following database schema:\n{schema_text}\n\nExternal Knowledge: {evidence}\n\nQuestion: {question}\n\nWrite a SQL query to answer the question."

        start_time = time.time()
        generated_sql = call_model(provider, client, model_name, system_prompt, user_prompt)
        duration = time.time() - start_time
        
        clean_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
        
        # Validation Run
        exec_success = False
        exec_result = None
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(clean_sql)
            exec_result = cursor.fetchall()
            conn.close()
            exec_success = True
        except Exception as e:
            exec_result = str(e)

        # Update Data
        item['generated_sql'] = clean_sql
        item['execution_result'] = str(exec_result)[:200]
        item['execution_success'] = exec_success
        item['time_taken'] = duration
        
        if "API_ERROR" not in clean_sql:
            repaired_count += 1
            # Save incrementally
            if repaired_count % 2 == 0:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
        
        # Pause to prevent rate limits
        time.sleep(1)

    # Final Save
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    
    print(f"\n   ✅ Repair Complete. Fixed {repaired_count}/{len(indices_to_repair)} items.")

def main():
    if not os.path.exists(BENCHMARKS_DIR):
        print(f"❌ Error: Directory {BENCHMARKS_DIR} not found.")
        return

    files = glob.glob(os.path.join(BENCHMARKS_DIR, "bird_results_*.json"))
    if not files:
        print("❌ No benchmark files found.")
        return

    for f in files:
        repair_file(f)

if __name__ == "__main__":
    main()