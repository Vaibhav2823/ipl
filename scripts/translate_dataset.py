# File: E:\ipl\scripts\translate_dataset.py
import json
import os
import time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# --- 1. SET YOUR GOOGLE API KEY ---
if "GOOGLE_API_KEY" not in os.environ:
    print("Error: GOOGLE_API_KEY not found. Please set the environment variable or paste it into the script.")
    exit()

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
INPUT_FILE = os.path.join(ROOT_DIR, 'gold_dataset.json')
OUTPUT_FILE = os.path.join(ROOT_DIR, 'gold_dataset_hindi.json')

# --- Initialize LLM ---
try:
    # Using a low temperature for accurate translation
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
except Exception as e:
    print(f"Error initializing LLM: {e}")
    exit()

# --- Translation Chain ---
translate_prompt = ChatPromptTemplate.from_template(
    "Translate the following English question about cricket into Hindi. Keep proper nouns (like player names 'Virat Kohli', team names 'Mumbai Indians') in English script if that is common usage, or use standard Hindi transliteration. Ensure the cricket terminology is natural for a Hindi speaker.\n\nEnglish Question: '{question}'\n\nHindi Translation:"
)
translate_chain = translate_prompt | llm

def translate_gold_dataset():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file {INPUT_FILE} not found.")
        return

    print(f"Reading from: {INPUT_FILE}")
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            gold_data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        return

    hindi_data = []
    total_count = len(gold_data)

    print(f"Found {total_count} entries. Starting translation...")

    for i, entry in enumerate(gold_data, start=1):
        english_q = entry.get('question', '')
        
        if not english_q:
            continue

        print(f"Translating {i}/{total_count}: {english_q[:50]}...")

        try:
            # Call LLM to translate
            response = translate_chain.invoke({"question": english_q})
            hindi_q = response.content.strip()
            
            # Create new entry with Hindi question
            # You can choose to keep both or replace. Here we keep both for clarity.
            new_entry = entry.copy()
            new_entry['question_hindi'] = hindi_q
            new_entry['question_english'] = english_q # Explicitly label English
            
            # Optional: If you want the main 'question' field to be Hindi, uncomment this:
            # new_entry['question'] = hindi_q 

            hindi_data.append(new_entry)
            
            # Sleep briefly to avoid rate limits if necessary
            # time.sleep(0.5) 

        except Exception as e:
            print(f"Error translating question: {e}")
            # Append original entry as fallback
            hindi_data.append(entry)

    # Write the new JSON file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(hindi_data, f, indent=2, ensure_ascii=False) # ensure_ascii=False is crucial for Hindi text
        print(f"\nTranslation complete! Saved to {OUTPUT_FILE}")
        
    except IOError as e:
        print(f"Error writing to output file {OUTPUT_FILE}: {e}")

if __name__ == "__main__":
    translate_gold_dataset()