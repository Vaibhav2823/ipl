# File: E:\ipl\scripts\create_json_dataset.py
import json
import os
import re

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# --- IMPORTANT ---
# Set the correct input file name here (the text file you've been generating)
INPUT_TXT_FILE = os.path.join(ROOT_DIR, 'dataset.txt') # Or 'op.txt' if you renamed it

# Output JSON file path
OUTPUT_JSON_FILE = os.path.join(ROOT_DIR, 'gold_dataset.json')

# --- MODIFIED REGEX ---
# Changed 'Answer:\n' to 'Answer:\s*'
# This allows the answer content to be on the same line OR a new line.
TRIPLET_REGEX = re.compile(
    r"Question:\s*(.*?)\s*SQL:\s*(.*?)\s*Answer:\s*(.*?)$", # <-- FIX IS HERE
    re.DOTALL | re.IGNORECASE
)

def parse_dataset_file():
    """
    Parses the custom .txt dataset file and converts it to a structured JSON.
    """
    print(f"Starting conversion...")
    print(f"Input file: {INPUT_TXT_FILE}")
    
    try:
        with open(INPUT_TXT_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: Input file not found at {INPUT_TXT_FILE}")
        return
    except Exception as e:
        print(f"ERROR reading file: {e}")
        return

    # Split the entire file into chunks based on the '---' separator
    chunks = content.split('---')
    
    json_data = []
    current_context_url = None # This will hold the "sticky" URL
    
    processed_triplets = 0
    skipped_chunks = 0

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Check if the chunk is JUST a URL
        if chunk.startswith('http://') or chunk.startswith('https://'):
            current_context_url = chunk.split('\n')[0].strip()
            print(f"\nFound new Context URL: {current_context_url}")
            
            # This logic assumes a URL chunk is ONLY a URL.
            # If a triplet is in the same chunk as a URL, it will be skipped.
            # Based on your file, URLs are on their own, separated by ---
            if len(chunk.split('\n')) == 1 and (chunk.endswith('.com') or chunk.endswith('.html') or '/live-cricket-scores/' in chunk):
                 continue
        
        # This chunk is not just a URL, so it should be a Question/SQL/Answer triplet
        match = TRIPLET_REGEX.search(chunk)
        
        if match:
            question = match.group(1).strip()
            sql_query = match.group(2).strip()
            answer_block = match.group(3).strip()
            
            # Format the answer as a list of strings, one per result line
            answer_list = [line.strip() for line in answer_block.split('\n') if line.strip()]
            
            # Create the JSON object for this entry
            entry = {
                "db_id": "ipl_db", # Your database name
                "context_url": current_context_url, # Assign the "sticky" URL
                "question": question,
                "query": sql_query,
                "answer": answer_list # Store the answer as a list
            }
            json_data.append(entry)
            processed_triplets += 1
        
        elif not (chunk.startswith('http') or chunk.startswith('#')):
            # This chunk was not empty, not a URL, and not a parsable triplet
            print(f"\nWARNING: Could not parse chunk: '{chunk[:50].replace(os.linesep, ' ')}...'")
            skipped_chunks += 1

    # Now, write the collected data to the JSON file
    try:
        with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
        print(f"\n--- Conversion Complete! ---")
        print(f"Successfully processed {processed_triplets} triplets.")
        if skipped_chunks > 0:
            print(f"Skipped {skipped_chunks} unparsable chunks (e.g., stray text or file fragments).")
        print(f"Gold dataset saved to: {OUTPUT_JSON_FILE}")
        
    except IOError as e:
        print(f"ERROR: Could not write JSON file to {OUTPUT_JSON_FILE}: {e}")
    except Exception as e:
        print(f"ERROR during JSON serialization: {e}")

if __name__ == "__main__":
    parse_dataset_file()