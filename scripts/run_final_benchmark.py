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
OUTPUT_DIR = os.path.join(ROOT_DIR, 'benchmarks')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- 2. KNOWLEDGE BASE ---
GLOBAL_PREAMBLE = """
You are an expert SQL writer for an IPL cricket database.
**IMPERATIVE RULE 1 (Result Limiting): This is a strict rule for how to use `LIMIT`.**
* **Case 1 (Explicit Number):** If the user asks for a specific number (e.g., 'top 5'), you MUST `ORDER BY` and use `LIMIT 5`.
* **Case 2 (Absolute Rank):** If the user asks for an absolute rank (e.g., 'highest', 'lowest', 'most'), you MUST `ORDER BY` and use `LIMIT 1`.
* **Case 3 (All Other Queries):** For any other query, you MUST return ALL matching rows. NEVER use a `LIMIT` clause.
IMPORTANT ADD-ON TO PREVIOUS RULES->You should return every instances of the absolute rank (e.g., 'highest', 'lowest', 'most') or the specified number.
**IMPERATIVE RULE 2: If specific context rules (like Team Mappings) are provided below, you MUST follow them strictly.**

The database has five tables:

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

   NOTE:
   - Total runs on a delivery = runs_scored + extra_runs.
   - Overs are 0-indexed.
   - ball_number stores only legal deliveries (1–6).

4. PlayerInMatch Table:
   - match_id (INTEGER, FK → Matches.match_id): Match reference.
   - player_id (TEXT, FK → Players.player_id): Player reference.
   - team_name (TEXT, NOT NULL): Team represented by the player in the match.
   - PRIMARY KEY (match_id, player_id)

5. FielderDismissals Table:
   - fielder_dismissal_id (INTEGER, PRIMARY KEY AUTOINCREMENT): Unique fielder dismissal ID.
   - delivery_id (INTEGER, FK → Deliveries.delivery_id): Delivery reference.
   - fielder_id (TEXT, FK → Players.player_id): Fielder involved in the dismissal.

GENERAL RULES:
- Always JOIN with the Players table to fetch player names.
- For wickets credited to bowlers, exclude:
  ('run out', 'retired hurt', 'obstructing the field', 'retired out').
- Do not assume a stored total_runs column; compute it when needed.

NOTE: 'match_date' (YYYY-MM-DD) is the source of truth for chronology.

Follow these additional crucial global rules:
1.  **JOINS FOR NAMES**: To get player NAMEs, JOIN with 'Players' using the ID column.
2.  **FIELDER INFO**: To find fielder(s), JOIN 'Deliveries' D -> 'FielderDismissals' F -> 'Players' P.
3.  **Bowler's Wickets**: Filter `wicket_type` correctly: `WHERE D.wicket_type IS NOT NULL AND D.wicket_type NOT IN ('run out', 'retired hurt', 'obstructing the field', 'retired out')`.
4.  **Over & Ball Numbering**: Overs are 0-indexed (0-19). `ball_number` stores the legal delivery number (1-6).
    * "Powerplay" means `WHERE D.over_number <= 5`.
    * "Death Overs" *typically* means `WHERE D.over_number >= 16`.
5.  **PLAYER NAME FILTERING**: Use `LIKE '%Name%'` when filtering 'Players' by name.
6.  **CHRONOLOGY & DEBUTS**: 
    * **NEVER** rely on `match_id` for order. `match_id` is arbitrary.
    * **ALWAYS** use `match_date` to determine the order of events.
    * **Finding a Debut**: The debut is the match with the **MIN(match_date)** for that player.
    * **CTE for Debut**: `WITH Debut AS (SELECT player_id, MIN(match_date) as debut_date FROM PlayerInMatch PM JOIN Matches M ON PM.match_id = M.match_id GROUP BY player_id) ...`

---
**CRICKET STATISTICS (CRITICAL!)**
Use these precise definitions for all statistical calculations. The 'Deliveries' table has columns: `runs_scored` (runs off bat), `wides`, `noballs`, `byes`, `legbyes`.

1.  **Legal Delivery (for Bowler & Team Overs)**: A ball that is NOT a wide or no-ball.
    * **SQL for Count:** `COUNT(CASE WHEN D.wides = 0 AND D.noballs = 0 THEN 1 END)`
    * **Bowler's Overs Bowled**: `COUNT(CASE WHEN D.wides = 0 AND D.noballs = 0 THEN 1 END) / 6.0`
    * **Team's Overs Faced**: `COUNT(CASE WHEN D.wides = 0 AND D.noballs = 0 THEN 1 END) / 6.0`
    * **Bowler's Runs Conceded**: `SUM(D.runs_scored + D.wides + D.noballs)` (Byes/Legbyes are NOT counted against the bowler).
    * **Bowler's Economy Rate**: `(SUM(D.runs_scored + D.wides + D.noballs) * 6.0) / COUNT(CASE WHEN D.wides = 0 AND D.noballs = 0 THEN 1 END)`

2.  **Ball Faced (by Batsman)**: A ball that is NOT a wide. (Batsmen *do* face no-balls, byes, and leg-byes).
    * **SQL for Count:** `COUNT(CASE WHEN D.wides = 0 THEN 1 END)`
    * **Batsman's Balls Faced**: `COUNT(CASE WHEN D.wides = 0 THEN 1 END)`
    * **Batsman's Strike Rate**: `SUM(D.runs_scored) * 100.0 / COUNT(CASE WHEN D.wides = 0 THEN 1 END)`
    * **Batsman's Dot Ball**: A "Ball Faced" (i.e., `D.wides = 0`) where the batsman scored zero runs (`D.runs_scored = 0`).
    * **Batsman's Average**: `SUM(D.runs_scored) / COUNT(CASE WHEN D.player_out_id = D.striker_id AND D.wicket_type NOT IN ('retired hurt', 'obstructing the field') THEN 1 END)`

3.  **Runs Scored**:
    * **Batsman's Runs**: `SUM(D.runs_scored)`
    * **Team's Total Runs**: `SUM(D.runs_scored + D.extra_runs)` (Use the `extra_runs` column as it is the sum of all extras).
---
"""
# SPECIFIC CONTEXT (Added by the router if needed)
CONTEXT_RULES = {
    "team_mapping": """
    - **IMPERATIVE Team Franchise Mappings**: This rule is mandatory for any query that groups by, filters on, or displays team names. You MUST use a CASE statement to group historical and modern names into a single franchise.
    - **DO NOT** group by or filter on the raw 'team1', 'team2', 'batting_team', 'bowling_team', or 'match_winner' columns directly. You MUST apply the CASE statement to them first.
    
    - **MAPPINGS:**
      - **Delhi Franchise (Use 'Delhi Capitals')**: 'Delhi Daredevils', 'Delhi Capitals'
      - **Punjab Franchise (Use 'Punjab Kings')**: 'Kings XI Punjab', 'Punjab Kings'
      - **Hyderabad Franchise (Use 'Sunrisers Hyderabad')**: 'Deccan Chargers', 'Sunrisers Hyderabad'
      - **Pune Franchise (Use 'Rising Pune Supergiant')**: 'Pune Warriors', 'Rising Pune Supergiant', 'Rising Pune Supergiants'
      - **Bengaluru Franchise (Use 'Royal Challengers Bengaluru')**: 'Royal Challengers Bangalore', 'Royal Challengers Bengaluru'
    
    - **Example SQL for Grouping:**
      `... GROUP BY (CASE WHEN T1.team_name IN ('Delhi Daredevils', 'Delhi Capitals') THEN 'Delhi Capitals' WHEN T1.team_name IN ('Kings XI Punjab', 'Punjab Kings') THEN 'Punjab Kings' ... ELSE T1.team_name END)`
    
    - **Example SQL for Filtering:**
      `... WHERE (CASE WHEN T1.batting_team IN ('Delhi Daredevils', 'Delhi Capitals') THEN 'Delhi Capitals' ELSE T1.batting_team END) = 'Delhi Capitals'`
    """
}

# --- 3. UTILITY FUNCTIONS ---

def clean_sql(raw_text):
    if not raw_text: return ""
    match = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw_text, re.DOTALL)
    if match: return match.group(1).strip()
    return raw_text.replace("SQLQuery:", "").strip()

def run_query_and_get_headers(db_path, sql, timeout=10):
    """Runs SQL and returns (result, error, headers)."""
    import threading
    
    result_container = {"result": None, "error": None, "headers": []}
    
    def target():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(sql)
            
            # Fetch Data
            result_container["result"] = cursor.fetchall()
            
            # Fetch Headers
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

    if thread.is_alive():
        return None, "ERROR: Query Timed Out", []
    if result_container["error"]:
        return None, f"EXECUTION_ERROR: {result_container['error']}", []
        
    return result_container["result"], None, result_container["headers"]

# --- 4. API INTERACTION FUNCTIONS (ROUTER + SQL GENERATOR) ---

def call_model_api(provider, client, model, system_prompt, user_prompt):
    """Unified handler for calling different APIs."""
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
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0
            )
            return response.content[0].text
    except Exception as e:
        return f"API_ERROR: {str(e)}"

def run_router_logic(provider, client, model, question):
    """Decides if 'team_mapping' context is needed."""
    router_system_instruction = (
        "You are a query analyzer for an IPL cricket database. "
        "Analyze the user question. Does it mention specific teams known to have changed names "
        "OR THEIR ABBREVIATIONS (e.g., Delhi, DC, DD, Punjab, PBKS, KXIP, Hyderabad, SRH, Pune, RPS, Bengaluru, Bangalore, RCB)? "
        "Respond strictly with only 'TRUE' or 'FALSE'."
    )
    
    response = call_model_api(provider, client, model, router_system_instruction, f"User Question: '{question}'")
    
    if response and "TRUE" in response.upper():
        return True
    return False

def run_benchmark_logic(provider, model, dataset, api_key):
    print(f"\n--- 🚀 Starting Benchmark (Resumable): {provider} / {model} ---")
    
    # 1. Setup Output File & Resume Logic
    safe_model_name = model.replace("/", "_").replace(":", "")
    filename = f"final_benchmark_{safe_model_name}.json"
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

    # Languages to test
    target_languages = ['question_english', 'question_hindi_1', 'question_hindi_2']

    for i, item in enumerate(dataset):
        
        for lang_key in target_languages:
            if lang_key not in item or not item[lang_key]:
                continue

            lang_label = lang_key.replace("question_", "").capitalize()
            unique_key = f"{i}_{lang_label}"

            # SKIP if already done
            if unique_key in processed_keys:
                continue

            question_text = item[lang_key]
            
            # --- EXTRACT REQUIRED COLUMNS FROM GOLD DATASET ---
            required_columns = item.get('column_names', [])

            print(f"\n[{i+1}/{len(dataset)}] [{lang_label}] Q: {question_text[:50]}...")
            start_time = time.time()

            # 1. Router
            requires_mapping = run_router_logic(provider, client, model, question_text)
            
            # 2. Build Prompt
            full_prompt = GLOBAL_PREAMBLE
            if requires_mapping:
                full_prompt += CONTEXT_RULES["team_mapping"]
            
            # 3. Generate SQL
            print(f"   > Generating SQL...")
            
            prompt_instruction = (
                f"Write a SQLite query for the following question. "
                f"Question: {question_text}. "
            )
            
            if required_columns:
                col_list_str = ", ".join(required_columns)
                prompt_instruction += (
                    f"\n\nCRITICAL CONSTRAINT: The final result set MUST have exactly these columns in this specific order: [{col_list_str}]. "
                    f"Use SQL ALIASES (AS ...) to match these names exactly."
                )
            
            prompt_instruction += " Output ONLY raw SQL code. No markdown formatting."
            
            raw_sql_output = call_model_api(provider, client, model, full_prompt, prompt_instruction)

            # 4. Execute & Capture Headers
            if "API_ERROR" in raw_sql_output:
                cleaned_sql = "API_ERROR"
                exec_result = raw_sql_output
                generated_columns = []
            else:
                cleaned_sql = clean_sql(raw_sql_output)
                # Execute and get headers
                exec_result, err, generated_columns = run_query_and_get_headers(DB_PATH, cleaned_sql, timeout=10)
                if err:
                    exec_result = err # Store error message as result
            
            duration = time.time() - start_time
            print(f"   > Done ({round(duration, 2)}s)")

            # 5. Save Result Structure
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
                
                "router_decision_mapping": requires_mapping,
                "time_taken": round(duration, 2)
            }
            
            results.append(new_entry)
            processed_keys.add(unique_key)

            # Write to file immediately (Incremental Saving)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=4, ensure_ascii=False)
            
            time.sleep(0.5)

    print(f"✅ Saved final results to: {filepath}")

# --- 5. MAIN EXECUTION ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Final IPL Benchmark")
    parser.add_argument("--provider", type=str, choices=["openai", "anthropic", "openrouter", "all"], help="Provider")
    parser.add_argument("--model", type=str, help="Specific model name", default=None)
    args = parser.parse_args()

    if not os.path.exists(INPUT_DATASET):
        print(f"❌ Error: Dataset not found at {INPUT_DATASET}")
        exit()

    with open(INPUT_DATASET, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    # 1. OpenAI
    if args.provider == "openai" or args.provider == "all":
        if "sk-" in OPENAI_API_KEY:
            run_benchmark_logic("openai", "gpt-4o", dataset, OPENAI_API_KEY)
        else: print("Skipping OpenAI (Key Missing)")

    # 2. Anthropic
    if args.provider == "anthropic" or args.provider == "all":
        if "sk-" in ANTHROPIC_API_KEY:
            # Using the stable ID we verified
            run_benchmark_logic("anthropic", "claude-3-7-sonnet-latest", dataset, ANTHROPIC_API_KEY)
        else: print("Skipping Anthropic (Key Missing)")

    # 3. OpenRouter
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
        print("Please specify --provider (openai, anthropic, openrouter, or all)")