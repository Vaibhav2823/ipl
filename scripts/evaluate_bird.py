import json
import sqlite3
import os
import glob
import time
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
BIRD_DB_DIR = os.path.join(ROOT_DIR, "bird", "dev_databases")
BENCHMARKS_DIR = os.path.join(ROOT_DIR, "benchmarks_bird")  # <--- Defined here
EVAL_DIR = os.path.join(ROOT_DIR, "benchmarks_bird_eval")

if not os.path.exists(EVAL_DIR):
    os.makedirs(EVAL_DIR)

def run_sql_with_timeout(db_path, sql, timeout=10):
    """Executes SQL with a strict timeout to prevent hanging."""
    import threading
    import queue

    result_queue = queue.Queue()

    def target():
        try:
            # Read-only mode to prevent locking
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute(sql)
            res = cursor.fetchall()
            conn.close()
            
            # Normalize data for comparison
            norm_res = set()
            for row in res:
                # Convert everything to string, lower case, stripped
                norm_row = tuple(str(x).strip().lower() if x is not None else "none" for x in row)
                norm_res.add(norm_row)
            result_queue.put(norm_res)
        except Exception as e:
            result_queue.put(f"ERROR: {str(e)}")

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        return "TIMEOUT"
    
    if not result_queue.empty():
        return result_queue.get()
    return "ERROR"

def evaluate_single_item(item):
    """Grades one single question."""
    db_id = item['db_id']
    gold_sql = item['gold_sql']
    gen_sql = item['generated_sql']
    
    db_path = os.path.join(BIRD_DB_DIR, db_id, f"{db_id}.sqlite")
    
    if not os.path.exists(db_path):
        return "DB_MISSING"

    # 1. Get Gold Answer (Ground Truth)
    gold_res = run_sql_with_timeout(db_path, gold_sql)
    
    # 2. Get Generated Answer
    gen_res = run_sql_with_timeout(db_path, gen_sql)

    # 3. Compare
    if isinstance(gen_res, str): # Error occurred
        if gen_res == "TIMEOUT": return "TIMEOUT"
        return "EXEC_ERROR"
    
    if isinstance(gold_res, str): # Gold failed (rare)
        return "GOLD_ERROR"

    return "CORRECT" if gold_res == gen_res else "INCORRECT"

def process_benchmark_file(filepath):
    filename = os.path.basename(filepath)
    eval_filename = filename.replace("bird_results_", "eval_").replace(".json", "_progress.json")
    eval_path = os.path.join(EVAL_DIR, eval_filename)
    
    print(f"\n📄 Processing: {filename}")

    # Load Data
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Load Existing Progress
    graded_results = {}
    if os.path.exists(eval_path):
        try:
            with open(eval_path, 'r', encoding='utf-8') as f:
                graded_results = json.load(f) # Dict mapping ID -> Result
            print(f"   🔄 Resuming: Found {len(graded_results)} already graded.")
        except:
            print("   ⚠️  Corrupt progress file. Starting fresh.")

    # Identify items left to grade
    # We map by index 'i' from the original list
    items_to_grade = []
    for i, item in enumerate(data):
        str_id = str(i)
        if str_id not in graded_results:
            items_to_grade.append((str_id, item))
            
    if not items_to_grade:
        print("   ✅ Already fully evaluated.")
        return calculate_final_stats(graded_results, filename)

    print(f"   🚀 Grading {len(items_to_grade)} remaining items...")

    for idx, (str_id, item) in enumerate(items_to_grade):
        # Grade
        result = evaluate_single_item(item)
        graded_results[str_id] = result
        
        # Print status
        sys.stdout.write(f"\r      Item {idx+1}/{len(items_to_grade)}: {result}")
        sys.stdout.flush()

        # Auto-Save every 10 items
        if (idx + 1) % 10 == 0:
            with open(eval_path, 'w', encoding='utf-8') as f:
                json.dump(graded_results, f, indent=4)
    
    # Final Save
    with open(eval_path, 'w', encoding='utf-8') as f:
        json.dump(graded_results, f, indent=4)
    
    print("\n   💾 Saved progress.")
    return calculate_final_stats(graded_results, filename)

def calculate_final_stats(graded_results, filename):
    total = len(graded_results)
    correct = sum(1 for v in graded_results.values() if v == "CORRECT")
    exec_err = sum(1 for v in graded_results.values() if v in ["EXEC_ERROR", "TIMEOUT"])
    
    acc = (correct / total * 100) if total else 0
    exec_rate = ((total - exec_err) / total * 100) if total else 0
    
    model_name = filename.replace("bird_results_", "").replace(".json", "")
    return [model_name, total, f"{exec_rate:.1f}%", f"{acc:.1f}%"]

def main():
    print("--- 🦅 BIRD Robust Evaluation ---")
    print(f"Results will be saved in: {EVAL_DIR}")
    
    if not os.path.exists(BENCHMARKS_DIR):
        print(f"❌ Error: Directory {BENCHMARKS_DIR} not found.")
        return

    # FIXED: Typo fixed here (BENCHMARK_DIR -> BENCHMARKS_DIR)
    files = glob.glob(os.path.join(BENCHMARKS_DIR, "bird_results_*.json"))
    if not files:
        print("❌ No benchmark files found.")
        return

    summary_table = []
    for f in files:
        summary_table.append(process_benchmark_file(f))
        
    # Print Final Table manually to avoid tabulate dependency issues
    print("\n" + "="*60)
    print(f"{'Model':<40} | {'Samples':<8} | {'Exec %':<10} | {'Accuracy':<10}")
    print("-" * 60)
    for row in summary_table:
        print(f"{row[0]:<40} | {row[1]:<8} | {row[2]:<10} | {row[3]:<10}")
    print("="*60)

if __name__ == "__main__":
    main()