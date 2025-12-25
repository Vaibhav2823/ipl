import json
import sqlite3
import os
import re
import time
import argparse
from openai import OpenAI
from anthropic import Anthropic

# --- 1. CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
INPUT_DATASET = os.path.join(ROOT_DIR, "gold_dataset_bilingual.json")
DB_PATH = os.path.join(ROOT_DIR, 'data', 'processed', 'ipl.db')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'benchmarks_raw')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- 2. BASIC KNOWLEDGE BASE (SCHEMA ONLY) ---
BASIC_SCHEMA = """
You are a SQL expert. Write a SQLite query for an IPL cricket database with the following EXACT schema:

1. Players Table:
   - player_id (TEXT, PRIMARY KEY): Unique identifier for a player.
   - player_name (TEXT, NOT NULL): Full name of the player.

2. Matches Table:
   - match_id (INTEGER, PRIMARY KEY): Unique identifier for the match.
   - season (TEXT, NOT NULL): IPL season (e.g., '2019').
   - match_date (TEXT, NOT NULL): Date of the match.
   - venue (TEXT, NOT NULL): Stadium name.
   - city (TEXT): City where the match was played.
   - stage (TEXT, DEFAULT 'Group'): Match stage (Group, Qualifier, Eliminator, Final).
   - team1 (TEXT, NOT NULL): First competing team.
   - team2 (TEXT, NOT NULL): Second competing team.
   - toss_winner (TEXT, NOT NULL): Team that won the toss.
   - toss_decision (TEXT, NOT NULL): Toss decision ('bat' or 'field').
   - match_winner (TEXT): Winning team.
   - result_type (TEXT): Result type (runs, wickets, tie, no result).
   - result_margin (INTEGER): Margin of victory.
   - player_of_match_id (TEXT, FK → Players.player_id): Player of the Match.
   - umpire1 (TEXT): First umpire.
   - umpire2 (TEXT): Second umpire.

3. Deliveries Table:
   - delivery_id (INTEGER, PRIMARY KEY AUTOINCREMENT): Unique delivery identifier.
   - match_id (INTEGER, FK → Matches.match_id): Match reference.
   - inning (INTEGER, NOT NULL): Inning number (1 or 2).
   - over_number (INTEGER, NOT NULL): Over number (0-indexed).
   - ball_number (INTEGER, NOT NULL): Legal ball number within the over (1–6).
   - batting_team (TEXT, NOT NULL): Batting team.
   - bowling_team (TEXT, NOT NULL): Bowling team.
   - striker_id (TEXT, FK → Players.player_id): Batter on strike.
   - non_striker_id (TEXT, FK → Players.player_id): Batter at non-striker’s end.
   - bowler_id (TEXT, FK → Players.player_id): Bowler.
   - runs_scored (INTEGER, NOT NULL): Runs scored off the bat.
   - extra_runs (INTEGER, NOT NULL): Total extras on the delivery.
   - wides (INTEGER, DEFAULT 0): Wide runs.
   - noballs (INTEGER, DEFAULT 0): No-ball runs.
   - byes (INTEGER, DEFAULT 0): Bye runs.
   - legbyes (INTEGER, DEFAULT 0): Leg-bye runs.
   - wicket_type (TEXT): Type of dismissal (NULL if no wicket).
   - player_out_id (TEXT, FK → Players.player_id): Dismissed player (if any).

4. PlayerInMatch Table:
   - match_id (INTEGER, FK → Matches.match_id): Match reference.
   - player_id (TEXT, FK → Players.player_id): Player reference.
   - team_name (TEXT, NOT NULL): Team represented by the player in the match.
   - PRIMARY KEY (match_id, player_id)

5. FielderDismissals Table:
   - fielder_dismissal_id (INTEGER, PRIMARY KEY AUTOINCREMENT): Unique fielder dismissal ID.
   - delivery_id (INTEGER, FK → Deliveries.delivery_id): Delivery reference.
   - fielder_id (TEXT, FK → Players.player_id): Fielder involved in the dismissal.

"""

# --- 3. UTILITY FUNCTIONS ---

def clean_sql(raw_text):
    if not raw_text: return ""
    match = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw_text, re.DOTALL)
    if match: return match.group(1).strip()
    return raw_text.replace("SQLQuery:", "").strip()

def run_query_and_get_headers(db_path, sql, timeout=10):
    import threading
    result_container = {"result": None, "error": None, "headers": []}
    
    def target():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(sql)
            result_container["result"] = cursor.fetchall()
            if cursor.description:
                result_container["headers"] = [desc[0] for desc in cursor.description]
            else:
                result_container["headers"] = []
            conn.close()
        except Exception as e:
            result_container["error"] = str(e)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout)

    if thread.is_alive(): return None, "ERROR: Query Timed Out", []
    if result_container["error"]: return None, f"EXECUTION_ERROR: {result_container['error']}", []
    return result_container["result"], None, result_container["headers"]

# --- 4. API INTERACTION FUNCTIONS ---

def call_model_api(provider, client, model, system_prompt, user_prompt):
    try:
        if provider == "openai" or provider == "openrouter":
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                extra_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "IPL-Benchmark"} if provider == "openrouter" else None
            )
            return response.choices[0].message.content
        elif provider == "anthropic":
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0
            )
            return response.content[0].text
    except Exception as e:
        return f"API_ERROR: {str(e)}"

def run_benchmark_logic(provider, model, dataset, api_key):
    print(f"\n--- 🚀 Starting RAW Benchmark: {provider} / {model} ---")
    
    # 1. Setup Output File & Resume Logic
    safe_model_name = model.replace("/", "_").replace(":", "")
    filename = f"raw_benchmark_{safe_model_name}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    results = []
    processed_keys = set() # Stores "id_language" strings

    # If file exists, load it to resume
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                results = existing_data
                for item in results:
                    # Create a unique key for ID + Language to track progress exactly
                    key = f"{item['id']}_{item['language']}"
                    processed_keys.add(key)
            print(f"🔄 Resuming... Found {len(results)} queries already completed.")
        except json.JSONDecodeError:
            print("⚠️ Warning: Output file corrupted or empty. Starting fresh.")

    # 2. Initialize Client
    client = None
    if provider == "openai": client = OpenAI(api_key=api_key)
    elif provider == "anthropic": client = Anthropic(api_key=api_key)
    elif provider == "openrouter": client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    target_languages = ['question_english', 'question_hindi_1', 'question_hindi_2']

    # 3. Main Loop
    for i, item in enumerate(dataset):
        for lang_key in target_languages:
            if lang_key not in item or not item[lang_key]: continue

            lang_label = lang_key.replace("question_", "").capitalize()
            unique_key = f"{i}_{lang_label}"

            # SKIP if already done
            if unique_key in processed_keys:
                continue

            question_text = item[lang_key]
            required_columns = item.get('column_names', [])

            print(f"\n[{i+1}/{len(dataset)}] [{lang_label}] Q: {question_text[:50]}...")
            start_time = time.time()

            # --- GENERATION ---
            user_instruction = f"Question: {question_text}\n"
            if required_columns:
                col_list_str = ", ".join(required_columns)
                user_instruction += (
                    f"\nCRITICAL CONSTRAINT: The final result set MUST have exactly these columns in this specific order: [{col_list_str}]. "
                    f"Use SQL ALIASES (AS ...) to match these names exactly."
                )
            user_instruction += "\nOutput ONLY raw SQL code. No markdown formatting."
            
            print(f"   > Generating SQL...")
            raw_sql_output = call_model_api(provider, client, model, BASIC_SCHEMA, user_instruction)

            # --- EXECUTION ---
            if "API_ERROR" in raw_sql_output:
                cleaned_sql = "API_ERROR"
                exec_result = raw_sql_output
                generated_columns = []
            else:
                cleaned_sql = clean_sql(raw_sql_output)
                exec_result, err, generated_columns = run_query_and_get_headers(DB_PATH, cleaned_sql, timeout=10)
                if err: exec_result = err
            
            duration = time.time() - start_time
            print(f"   > Done ({round(duration, 2)}s)")

            # --- SAVE IMMEDIATELY ---
            new_entry = {
                "id": i,
                "language": lang_label,
                "question": question_text,
                "gold_sql": item.get('query'),
                "gold_answer": str(item.get('answer')),
                "gold_column_names": item.get('column_names', []),
                "model": model,
                "generated_sql": cleaned_sql,
                "generated_answer": str(exec_result),
                "generated_column_names": generated_columns,
                "mode": "RAW_NO_ROUTER",
                "time_taken": round(duration, 2)
            }
            
            results.append(new_entry)
            processed_keys.add(unique_key) # Mark as done in memory

            # Write to file immediately
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=4, ensure_ascii=False)
            
            time.sleep(0.5) # Slight pause to be polite to API

    print(f"✅ Benchmark Complete. Results saved to: {filepath}")

# --- 5. MAIN EXECUTION ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Raw IPL Benchmark (Resumable)")
    parser.add_argument("--provider", type=str, choices=["openai", "anthropic", "openrouter", "all"], help="Provider")
    parser.add_argument("--model", type=str, help="Specific model name", default=None)
    args = parser.parse_args()

    if not os.path.exists(INPUT_DATASET):
        print(f"❌ Error: Dataset not found at {INPUT_DATASET}")
        exit()

    with open(INPUT_DATASET, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    if args.provider == "openai" or args.provider == "all":
        if "sk-" in OPENAI_API_KEY: run_benchmark_logic("openai", "gpt-4o", dataset, OPENAI_API_KEY)
        else: print("Skipping OpenAI (Key Missing)")

    if args.provider == "anthropic" or args.provider == "all":
        if "sk-" in ANTHROPIC_API_KEY: run_benchmark_logic("anthropic", "claude-3-7-sonnet-latest", dataset, ANTHROPIC_API_KEY)
        else: print("Skipping Anthropic (Key Missing)")

    if args.provider == "openrouter" or args.provider == "all":
        if "sk-" in OPENROUTER_API_KEY:
            if args.model:
                run_benchmark_logic("openrouter", args.model, dataset, OPENROUTER_API_KEY)
            else:
                print("Running ALL default OpenRouter models...")
                run_benchmark_logic("openrouter", "meta-llama/llama-3.1-8b-instruct", dataset, OPENROUTER_API_KEY)
                run_benchmark_logic("openrouter", "qwen/qwen-2.5-7b-instruct", dataset, OPENROUTER_API_KEY)
                run_benchmark_logic("openrouter", "google/gemma-2-9b-it", dataset, OPENROUTER_API_KEY)
                run_benchmark_logic("openrouter", "deepseek/deepseek-r1", dataset, OPENROUTER_API_KEY)
        else: print("Skipping OpenRouter (Key Missing)")

    if not args.provider:
        print("Please specify --provider")