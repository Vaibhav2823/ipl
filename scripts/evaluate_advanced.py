import json
import os
import ast
import glob
import datetime
import re
import sys
from tabulate import tabulate

# 1. FORCE UTF-8 OUTPUT (Helps prevents some encoding errors)
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
GOLD_FILE = os.path.join(ROOT_DIR, "gold_dataset_bilingual.json")
BENCHMARK_DIR = os.path.join(ROOT_DIR, "benchmarks")
REPORT_FILE = os.path.join(ROOT_DIR, "evaluation_summary_all_models.txt")

# Error Tolerance Settings
TOLERANCE_MAP = {
    "STRIKE_RATE": 1.0,
    "AVERAGE": 1.0,
    "RUNS_HIGH": 1.0,
    "RUNS_LOW": 1.0,
    "DEFAULT_NUM": 1.0,
}

# --- UTILITY FUNCTIONS ---

def clean_str(s):
    return str(s).strip().lower()

def parse_data(data):
    """Robust parser for data lists from string or list format."""
    if data is None: return []
    
    if isinstance(data, str):
        if "ERROR" in data or "Time Out" in data: return None
        try:
            data = ast.literal_eval(data)
        except:
            return None

    if isinstance(data, list):
        cleaned_rows = []
        for item in data:
            if isinstance(item, str):
                try:
                    val = ast.literal_eval(item)
                    if not isinstance(val, (list, tuple)): val = [val]
                    cleaned_rows.append(tuple(val))
                except:
                    cleaned_rows.append((item,))
            elif isinstance(item, (list, tuple)):
                cleaned_rows.append(tuple(item))
            else:
                cleaned_rows.append((item,))
        return cleaned_rows
    return []

def determine_col_type(col_name):
    cn = col_name.lower()
    if any(x in cn for x in ["strike", "rate", "economy"]): return "STRIKE_RATE"
    if any(x in cn for x in ["average", "avg"]): return "AVERAGE"
    if any(x in cn for x in ["run", "score", "total"]): return "RUNS"
    if any(x in cn for x in ["name", "player", "team", "venue", "city"]): return "STRING"
    return "DEFAULT_NUM"

def check_value_match(gold_val, gen_val, col_type):
    if gold_val is None or gen_val is None:
        return gold_val == gen_val
    
    if col_type == "STRING" or isinstance(gold_val, str):
        return clean_str(gold_val) == clean_str(gen_val)

    try:
        g = float(gold_val)
        v = float(gen_val)
        diff = abs(g - v)
        
        if col_type == "STRIKE_RATE": return diff <= TOLERANCE_MAP["STRIKE_RATE"]
        if col_type == "AVERAGE": return diff <= TOLERANCE_MAP["AVERAGE"]
        if col_type == "RUNS": 
            return diff <= (TOLERANCE_MAP["RUNS_LOW"] if g <= 100 else TOLERANCE_MAP["RUNS_HIGH"])
        return diff <= TOLERANCE_MAP["DEFAULT_NUM"]
    except:
        return clean_str(gold_val) == clean_str(gen_val)

# --- ERROR ANALYSIS LOGIC ---

def categorize_sql_error(sql, q_text):
    """
    Analyzes the SQL and Question to identify specific failure modes.
    Returns a list of error categories found.
    """
    sql = str(sql).upper()
    q_text = str(q_text).lower()
    detected_errors = []

    # 1. Hallucinated Schema (Fake columns)
    if any(x in sql for x in ["TOTAL_RUNS", "BATSMAN_RUNS", "MATCH_YEAR", "WINNER_ID", "CITY_NAME", "VENUE_ID"]):
        detected_errors.append("Hallucinated Schema")

    # 2. Legal Delivery Logic (Asking for Econ/SR but not filtering wides)
    if ("economy" in q_text or "strike rate" in q_text) and "WIDES" not in sql:
        detected_errors.append("Legal Delivery Logic")

    # 3. Team Entity Resolution (Mentions historical team but no CASE statement)
    if any(t in q_text for t in ["delhi", "punjab", "bangalore", "hyderabad", "pune"]):
        if "CASE" not in sql and any(x in sql for x in ["DAREDEVILS", "KINGS XI", "BANGALORE", "CHARGERS"]):
            detected_errors.append("Team Entity Resolution")

    # 4. Phase Filtering (Powerplay/Death asked but no over_number check)
    if ("powerplay" in q_text or "death" in q_text) and "OVER_NUMBER" not in sql:
        detected_errors.append("Phase Filtering")

    # 5. Incorrect Aggregation (Asked for Avg, gave Sum)
    if "average" in q_text and "SUM(" in sql and "/" not in sql:
         detected_errors.append("Incorrect Aggregation")

    return detected_errors

# --- MAIN EVALUATION FUNCTION ---

def evaluate_single_model(filepath, gold_map):
    """Evaluates a single model file and returns statistics and a text report block."""
    filename = os.path.basename(filepath)
    model_name = filename.replace("final_benchmark_", "").replace(".json", "")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        gen_data = json.load(f)
    
    stats = {
        "Total": {"count": 0, "exec": 0, "data_match": 0, "schema_match": 0, "time_sum": 0},
        "English": {"count": 0, "exec": 0, "data_match": 0},
        "Hindi_1": {"count": 0, "exec": 0, "data_match": 0},
        "Hindi_2": {"count": 0, "exec": 0, "data_match": 0}
    }
    
    # Generic Evaluation Counters
    basic_failures = {"Schema Mismatch": 0, "Row Count Mismatch": 0, "Value Mismatch": 0, "Execution Error": 0}
    
    # NEW: Specific Forensic Counters
    forensic_failures = {
        "Hallucinated Schema": 0, 
        "Legal Delivery Logic": 0, 
        "Team Entity Resolution": 0, 
        "Phase Filtering": 0, 
        "Incorrect Aggregation": 0
    }

    for item in gen_data:
        q_id = item.get('id')
        lang = item.get('language', 'English')
        time_taken = item.get('time_taken', 0)
        
        if q_id not in gold_map: continue
        gold_item = gold_map[q_id]
        
        # Update Basic Counts
        stats["Total"]["count"] += 1
        stats["Total"]["time_sum"] += time_taken
        if lang in stats: stats[lang]["count"] += 1

        # Schema Check
        gold_cols = gold_item.get('column_names', [])
        gen_cols = item.get('generated_column_names', [])
        
        schema_is_correct = False
        if gen_cols and len(gen_cols) == len(gold_cols):
             if [c.lower() for c in gen_cols] == [c.lower() for c in gold_cols]:
                 stats["Total"]["schema_match"] += 1
                 schema_is_correct = True

        # Data Check
        gold_rows = parse_data(gold_item.get('answer'))
        gen_rows = parse_data(item.get('generated_answer'))
        
        # 1. Execution Success
        is_exec_success = False
        if gen_rows is not None:
            is_exec_success = True
            stats["Total"]["exec"] += 1
            if lang in stats: stats[lang]["exec"] += 1
            
            # 2. Data Matching
            match_score = 0.0
            if gold_rows:
                col_types = [determine_col_type(c) for c in gold_cols]
                matches = 0
                matched_indices = set()
                
                for g_row in gold_rows:
                    for idx, gen_row in enumerate(gen_rows):
                        if idx in matched_indices: continue
                        if len(g_row) != len(gen_row): continue
                        
                        row_is_match = True
                        for c_idx, (gv, gv_gen) in enumerate(zip(g_row, gen_row)):
                            ctype = col_types[c_idx] if c_idx < len(col_types) else "DEFAULT_NUM"
                            if not check_value_match(gv, gv_gen, ctype):
                                row_is_match = False
                                break
                        
                        if row_is_match:
                            matches += 1
                            matched_indices.add(idx)
                            break
                
                match_score = matches / len(gold_rows)
                stats["Total"]["data_match"] += match_score
                if lang in stats: stats[lang]["data_match"] += match_score
                
                # Categorize Basic Failures
                if match_score < 1.0:
                    if not schema_is_correct:
                         basic_failures["Schema Mismatch"] += 1
                    elif len(gold_rows) != len(gen_rows):
                        basic_failures["Row Count Mismatch"] += 1
                    else:
                        basic_failures["Value Mismatch"] += 1
        else:
            basic_failures["Execution Error"] += 1

        # --- RUN FORENSIC ERROR ANALYSIS ---
        # We run this if there was an execution error OR data match score < 1.0
        if not is_exec_success or (gen_rows and match_score < 1.0):
            generated_sql = item.get('generated_sql', '')
            question_text = item.get('question', '') + " " + lang 
            
            errors_found = categorize_sql_error(generated_sql, question_text)
            for err_cat in errors_found:
                forensic_failures[err_cat] += 1

    # --- Generate Report Block ---
    avg_time = stats["Total"]["time_sum"] / stats["Total"]["count"] if stats["Total"]["count"] else 0
    total_failures = stats["Total"]["count"] - stats["Total"]["data_match"] 
    if total_failures < 1: total_failures = 1 

    report_lines = [
        f"MODEL: {model_name}",
        "-"*40,
        f"Total Queries: {stats['Total']['count']}",
        f"Avg Latency:   {avg_time:.2f}s per query",
        "",
        "METRICS:",
        f"  Execution Success:  {stats['Total']['exec']}/{stats['Total']['count']} ({stats['Total']['exec']/stats['Total']['count']*100:.1f}%)",
        f"  Schema Compliance:  {stats['Total']['schema_match']}/{stats['Total']['count']} ({stats['Total']['schema_match']/stats['Total']['count']*100:.1f}%)",
        f"  Data Match Score:   {stats['Total']['data_match']:.1f}/{stats['Total']['count']} ({stats['Total']['data_match']/stats['Total']['count']*100:.1f}%)",
        "",
        "LANGUAGE BREAKDOWN (Data Match %):",
    ]
    
    for lang in ["English", "Hindi_1", "Hindi_2"]:
        if stats[lang]["count"] > 0:
            dm_p = stats[lang]["data_match"] / stats[lang]["count"] * 100
            report_lines.append(f"  {lang:<10}: {dm_p:.1f}%")

    report_lines.append("")
    report_lines.append("BASIC FAILURE COUNTS:")
    for err, count in basic_failures.items():
        if count > 0:
            report_lines.append(f"  {err:<20}: {count}")

    report_lines.append("")
    report_lines.append("FORENSIC ERROR ANALYSIS (Semantic Causes):")
    for err, count in forensic_failures.items():
        pct = (count / total_failures) * 100
        if count > 0:
            report_lines.append(f"  {err:<25}: {count} ({pct:.1f}% of failures)")
    
    report_lines.append("\n" + "="*60 + "\n")
    
    return model_name, stats, "\n".join(report_lines)

def main():
    print("--- Starting Comprehensive Evaluation & Error Analysis ---")
    
    if not os.path.exists(GOLD_FILE):
        print(f"Error: Gold file not found at {GOLD_FILE}")
        return

    with open(GOLD_FILE, 'r', encoding='utf-8') as f:
        gold_data = {i: item for i, item in enumerate(json.load(f))}
        
    files = glob.glob(os.path.join(BENCHMARK_DIR, "final_benchmark_*.json"))
    
    if not files:
        print("Error: No benchmark files found.")
        return

    summary_table = []
    full_report_text = [f"CRICBENCH COMPREHENSIVE REPORT\nGenerated: {datetime.datetime.now()}\n" + "="*60 + "\n"]

    for f in files:
        model_name, st, report_text = evaluate_single_model(f, gold_data)
        full_report_text.append(report_text)
        
        tot = st["Total"]["count"]
        ex = st["Total"]["exec"] / tot * 100 if tot else 0
        dt = st["Total"]["data_match"] / tot * 100 if tot else 0
        sch = st["Total"]["schema_match"] / tot * 100 if tot else 0
        
        # English vs Hindi Average
        eng_dt = st["English"]["data_match"] / st["English"]["count"] * 100 if st["English"]["count"] else 0
        
        hin_total_count = st["Hindi_1"]["count"] + st["Hindi_2"]["count"]
        hin_total_score = st["Hindi_1"]["data_match"] + st["Hindi_2"]["data_match"]
        hin_dt = hin_total_score / hin_total_count * 100 if hin_total_count else 0
        
        summary_table.append([model_name, f"{ex:.1f}%", f"{sch:.1f}%", f"{dt:.1f}%", f"{eng_dt:.1f}%", f"{hin_dt:.1f}%"])
        
    # Print Summary Table to Console
    print(tabulate(summary_table, headers=["Model", "Exec %", "Schema %", "Data %", "Eng %", "Hindi %"], tablefmt="grid"))
    
    # Save Full Report
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(full_report_text))
        
    print(f"\nFull report with Error Analysis saved to: {REPORT_FILE}")

if __name__ == "__main__":
    main()