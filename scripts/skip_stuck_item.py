import json
import os

# Define the file path for the stuck model
# Make sure this matches your actual file name in 'benchmarks_bird'
RESULT_FILE = "benchmarks_bird/bird_results_qwen_qwen-2.5-7b-instruct.json"

def skip_item():
    if not os.path.exists(RESULT_FILE):
        print(f"❌ Error: File not found: {RESULT_FILE}")
        return

    with open(RESULT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Calculate which ID we are skipping
    next_id = len(data)
    print(f"⚠️  Current count: {len(data)} items.")
    print(f"⏭️  Skipping Item ID {next_id} (The one getting stuck)...")

    # Create a dummy skipped entry
    dummy_entry = {
        "id": next_id,
        "db_id": "SKIPPED_MANUALLY",
        "question": "SKIPPED DUE TO HANG",
        "gold_sql": "",
        "generated_sql": "SELECT 'SKIPPED';",
        "execution_result": "MANUAL_SKIP",
        "execution_success": False,
        "time_taken": 0.0
    }

    # Append and Save
    data.append(dummy_entry)
    
    with open(RESULT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

    print(f"✅ Success! File now has {len(data)} items.")
    print("🚀 You can now restart the benchmark script. It will resume at item", next_id + 2)

if __name__ == "__main__":
    skip_item()