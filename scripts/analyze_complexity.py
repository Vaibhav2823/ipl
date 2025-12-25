import json
import re
import os

# --- PATH CONFIGURATION (Matches your benchmark script) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # e.g. E:\ipl\scripts
ROOT_DIR = os.path.dirname(BASE_DIR)                  # e.g. E:\ipl
INPUT_DATASET = os.path.join(ROOT_DIR, "gold_dataset_bilingual.json")

def analyze_sql_complexity(dataset_path):
    if not os.path.exists(dataset_path):
        print(f"❌ Error: Dataset not found at {dataset_path}")
        return

    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = len(data)
    stats = {
        "joins": 0,
        "nested": 0,
        "aggregations": 0,
        "temporal": 0,
        "franchise": 0,
        "derived": 0
    }

    # Keywords for Franchise Normalization (Historical names)
    franchise_keywords = [
        "delhi daredevils", "kings xi punjab", "deccan chargers", 
        "pune warriors", "rising pune", "royal challengers bangalore"
    ]
    
    # Keywords for Derived Metrics
    derived_keywords = ["average", "economy", "strike rate", "net run rate"]

    print(f"Analyzing {total} queries from: {dataset_path}...\n")

    for entry in data:
        sql = entry.get('query', '').upper()
        # Combine English and Hindi questions to check intent
        q_text = (entry.get('question_english', '') + " " + 
                  entry.get('question_hindi_1', '')).lower()
        
        # 1. Structural: Joins (Count occurrences of 'JOIN')
        if sql.count(" JOIN ") >= 1:
            stats["joins"] += 1

        # 2. Structural: Nested Queries (SELECT inside parens OR WITH clause)
        if re.search(r'\(\s*SELECT', sql) or "WITH " in sql:
            stats["nested"] += 1

        # 3. Structural: Aggregations
        if "GROUP BY" in sql or "HAVING" in sql:
            stats["aggregations"] += 1

        # 4. Domain: Temporal Filters
        if any(x in sql for x in ["MATCH_DATE", "SEASON", "YEAR", "DATE("]):
            stats["temporal"] += 1

        # 5. Domain: Franchise Normalization (CASE logic or Historical Name usage)
        if "CASE WHEN" in sql or any(k in q_text for k in franchise_keywords):
            stats["franchise"] += 1
            
        # 6. Domain: Derived Metrics (Math in SQL or keywords in Q)
        if any(k in q_text for k in derived_keywords) or ("/" in sql and "COUNT" in sql):
            stats["derived"] += 1

    # --- OUTPUT LATEX TABLE ROWS ---
    print("="*50)
    print("COPY THE LINES BELOW INTO YOUR LATEX TABLE:")
    print("="*50)
    
    rows = [
        ("Multi-table Joins", stats["joins"]),
        ("Nested Queries / CTEs", stats["nested"]),
        ("Aggregations (Group By/Having)", stats["aggregations"]),
        ("Temporal Filtering", stats["temporal"]),
        ("Franchise Normalization", stats["franchise"]),
        ("Derived Metrics (SR, Econ)", stats["derived"])
    ]
    
    for label, count in rows:
        pct = (count / total) * 100
        # Format: Label & Count & Percentage% \\
        print(f"{label} & {count} & {pct:.1f}\\% \\\\")
    print("="*50)

if __name__ == "__main__":
    analyze_sql_complexity(INPUT_DATASET)