import subprocess
import time
import os
import sys

# --- CONFIGURATION ---
# List of models to run [Provider, Model_ID]
MODELS = [
    ("openai", "gpt-4o"),
    ("anthropic", "claude-3-7-sonnet-latest"),
    ("openrouter", "meta-llama/llama-3.1-8b-instruct"),
    ("openrouter", "qwen/qwen-2.5-7b-instruct"),
    ("openrouter", "google/gemma-2-9b-it"),
    ("openrouter", "deepseek/deepseek-r1")
]

# Ensure logs directory exists
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def run_parallel():
    processes = []
    print(f"--- 🚀 Launching {len(MODELS)} Benchmarks in Parallel ---")
    print(f"Logs will be saved to the '{LOG_DIR}/' directory.\n")

    for provider, model in MODELS:
        # Create a safe filename for the log
        safe_name = model.replace("/", "_").replace(":", "")
        log_file_path = os.path.join(LOG_DIR, f"run_{safe_name}.log")
        
        # Open log file for writing
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            print(f"   > Starting {model}...")
            
            # Construct command
            cmd = [
                sys.executable, "scripts/benchmark_bird.py",
                "--provider", provider,
                "--model", model
            ]
            
            # Spawn process (non-blocking)
            # stdout and stderr are redirected to the log file
            p = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
            processes.append((model, p))
            
            # Small delay to prevent API rate limit spikes at startup
            time.sleep(2)

    print("\n✅ All processes launched! Waiting for completion...")
    print("You can monitor progress by checking the log files.\n")

    # Monitor Loop
    while True:
        all_done = True
        running_count = 0
        
        for model, p in processes:
            if p.poll() is None:  # Process is still running
                all_done = False
                running_count += 1
        
        # Update status on the same line
        sys.stdout.write(f"\r⏳ Models running: {running_count} / {len(MODELS)}   ")
        sys.stdout.flush()
        
        if all_done:
            break
        
        time.sleep(5)

    print("\n\n🎉 All benchmarks finished!")

if __name__ == "__main__":
    run_parallel()