# File: E:\ipl\scripts\translate_dataset_malayalam.py
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
# CHANGE: Output file set to Malayalam
OUTPUT_FILE = os.path.join(ROOT_DIR, 'gold_dataset_malayalam.json')

# --- Initialize LLM ---
try:
    # Using gemini-2.5-pro with low temperature for translation precision
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.1)
except Exception as e:
    print(f"Error initializing LLM: {e}")
    exit()

# --- Translation Chain ---
# CHANGE: Prompt updated for Malayalam context
translate_prompt = ChatPromptTemplate.from_template(
    "Translate the following English question about cricket into Malayalam.\n"
    "Guidelines:\n"
    "1. Keep proper nouns (like player names 'Virat Kohli', team names 'Mumbai Indians') in English script if strictly necessary, but standard Malayalam transliteration is preferred.\n"
    "2. Ensure cricket terminology (Runs, Wickets, Overs) feels natural to a Malayalam speaker.\n\n"
    "English Question: '{question}'\n\n"
    "Malayalam Translation:"
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

    malayalam_data = []
    total_count = len(gold_data)

    print(f"Found {total_count} entries. Starting Malayalam translation...")

    for i, entry in enumerate(gold_data, start=1):
        english_q = entry.get('question', '')
        
        if not english_q:
            continue

        print(f"Translating {i}/{total_count}: {english_q[:50]}...")

        try:
            # Call LLM to translate
            response = translate_chain.invoke({"question": english_q})
            malayalam_q = response.content.strip()
            
            # Create new entry with Malayalam question
            new_entry = entry.copy()
            # CHANGE: storing in 'question_malayalam'
            new_entry['question_malayalam'] = malayalam_q
            new_entry['question_english'] = english_q 
            
            malayalam_data.append(new_entry)
            
            # Optional: Sleep to respect rate limits if processing huge datasets
            # time.sleep(0.2) 

        except Exception as e:
            print(f"Error translating question: {e}")
            # Append original entry as fallback
            malayalam_data.append(entry)

    # Write the new JSON file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            # CHANGE: ensure_ascii=False is critical for Malayalam characters to render correctly
            json.dump(malayalam_data, f, indent=2, ensure_ascii=False) 
        print(f"\nTranslation complete! Saved to {OUTPUT_FILE}")
        
    except IOError as e:
        print(f"Error writing to output file {OUTPUT_FILE}: {e}")

if __name__ == "__main__":
    translate_gold_dataset()