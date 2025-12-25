import json
import os
import glob
import sys
import re

# 1. FIX UNICODE ERROR (Force UTF-8 output for Windows terminals)
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHMARKS_DIR = os.path.join(os.path.dirname(BASE_DIR), "benchmarks")

def normalize_answer(ans):
    """
    Cleans up SQLite output strings like "[('Value',)]" to just "value"
    for fair comparison with gold standard.
    """
    if ans is None: return ""
    ans = str(ans).strip().lower()
    
    # Check for specific SQL error messages
    if "error" in ans or "timeout" in ans:
        return "ERROR_FLAG"
        
    # Remove Python list/tuple syntax: [, ], (, ), comma, single/double quotes
    ans = re.sub(r"[\[\]\(\),'\"]", "", ans)
    
    # Handle floats: 150.0 -> 150 (if integer equivalent)
    try:
        val = float(ans)
        if val.is_integer():
            return str(int(val))
        return str(val)
    except:
        pass
        
    return ans.strip()

def analyze_all_errors():
    json_files = glob.glob(os.path.join(BENCHMARKS_DIR, "*.json"))
    
    if not json_files:
        print(f"[ERROR] No benchmark files found in {BENCHMARKS_DIR}")
        return

    print(f"[INFO] Found {len(json_files)} model files. Analyzing with SMART COMPARISON...\n")

    all_model_stats = {}

    for filepath in json_files:
        filename = os.path.basename(filepath)
        model_name = filename.replace("final_benchmark_", "").replace(".json", "")
        
        # Create readable short names
        if "llama" in model_name: short_name = "Llama-3.1"
        elif "claude" in model_name: short_name = "Claude-3.7"
        elif "gpt-4o" in model_name: short_name = "GPT-4o"
        elif "deepseek" in model_name: short_name = "DeepSeek-R1"
        elif "gemma" in model_name: short_name = "Gemma-2-9B"
        elif "qwen" in model_name: short_name = "Qwen-2.5"
        else: short_name = model_name[:10]

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to read {filename}: {e}")
            continue

        stats = {
            "total_queries": len(data),
            "total_errors": 0,
            "hallucination": 0,
            "legal_ball": 0,
            "team_mapping": 0,
            "phase_filter": 0,
            "aggregation": 0
        }

        for entry in data:
            raw_gen = entry.get('generated_answer', '')
            raw_gold = entry.get('gold_answer', '')
            
            # --- SMART COMPARISON ---
            norm_gen = normalize_answer(raw_gen)
            norm_gold = normalize_answer(raw_gold)
            
            # Error if normalized strings differ OR if it explicitly failed execution
            is_error = (norm_gen != norm_gold) or (norm_gen == "ERROR_FLAG")
            
            if not is_error:
                continue # Skip correct answers

            stats["total_errors"] += 1
            
            # --- FORENSIC ANALYSIS OF SQL ---
            sql = str(entry.get('generated_sql', '')).upper()
            q_text = str(entry.get('question', '')).lower() + " " + str(entry.get('language', '')).lower()

            # 1. Hallucinations
            if any(x in sql for x in ["TOTAL_RUNS", "BATSMAN_RUNS", "MATCH_YEAR", "WINNER_ID", "CITY_NAME"]):
                stats["hallucination"] += 1

            # 2. Legal Delivery Logic (Asking for Econ/SR but not filtering wides)
            if ("economy" in q_text or "strike rate" in q_text) and "WIDES" not in sql:
                stats["legal_ball"] += 1

            # 3. Team Mapping (Mentions team name but no CASE statement)
            if any(t in q_text for t in ["delhi", "punjab", "bangalore", "hyderabad", "pune"]):
                if "CASE" not in sql and any(x in sql for x in ["DAREDEVILS", "KINGS XI", "BANGALORE", "CHARGERS"]):
                    stats["team_mapping"] += 1

            # 4. Phase Filtering (Powerplay/Death)
            if ("powerplay" in q_text or "death" in q_text) and "OVER_NUMBER" not in sql:
                stats["phase_filter"] += 1

            # 5. Aggregation Mismatch
            if "average" in q_text and "SUM(" in sql and "/" not in sql:
                 stats["aggregation"] += 1

        all_model_stats[short_name] = stats

    # --- PRINT CONSOLIDATED SUMMARY ---
    print("="*105)
    print(f"{'Model':<15} | {'TotErr':<7} | {'Halluc':<7} | {'LegalBall':<10} | {'TeamMap':<8} | {'Phase':<6} | {'Aggreg':<6}")
    print("-" * 105)
    
    for name, s in all_model_stats.items():
        print(f"{name:<15} | {s['total_errors']:<7} | {s['hallucination']:<7} | {s['legal_ball']:<10} | {s['team_mapping']:<8} | {s['phase_filter']:<6} | {s['aggregation']:<6}")
    print("="*105)

    # --- GENERATE LATEX ROWS FOR ALL MODELS ---
    print("\n\n=== LATEX TABLE DATA FOR ALL MODELS ===")
    
    for name, s in all_model_stats.items():
        total = s['total_errors']
        if total == 0: 
            print(f"\n% {name}: Perfect Score (0 Errors)")
            continue
            
        print(f"\n% Stats for {name} (N={total} errors)")
        print(f"Hallucinated Schema & {s['hallucination']} & {(s['hallucination']/total)*100:.1f}\\% \\\\")
        print(f"Legal Delivery Logic & {s['legal_ball']} & {(s['legal_ball']/total)*100:.1f}\\% \\\\")
        print(f"Team Entity Resolution & {s['team_mapping']} & {(s['team_mapping']/total)*100:.1f}\\% \\\\")
        print(f"Phase Filtering & {s['phase_filter']} & {(s['phase_filter']/total)*100:.1f}\\% \\\\")
        print(f"Incorrect Aggregation & {s['aggregation']} & {(s['aggregation']/total)*100:.1f}\\% \\\\")

if __name__ == "__main__":
    analyze_all_errors()