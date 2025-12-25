# File: E:\ipl\scripts\verify_dataset.py
# This script reads your gold_dataset.json, feeds the SQL query from each
# entry to an LLM (with the schema) to get a "round-trip" natural
# language question. It saves the comparison to a text file for manual review.

import logging
import os
import re
import sqlite3
import time
import json
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import create_sql_query_chain
from langchain.chains.structured_output import create_structured_output_runnable
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

# --- 1. SET YOUR GOOGLE API KEY ---
if "GOOGLE_API_KEY" not in os.environ:
    # os.environ["GOOGLE_API_KEY"] = "YOUR_GOOGLE_API_KEY"
    print("Error: GOOGLE_API_KEY not found. Please set the environment variable or paste it into the script.")
    exit()

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
# --- Input file: Your verified "gold" dataset ---
GOLD_DATASET_PATH = os.path.join(ROOT_DIR, 'gold_dataset.json') 
# --- Output file: The file for you to review ---
VERIFICATION_OUTPUT_PATH = os.path.join(ROOT_DIR, 'verification_output.txt') 
# --- Log file for this script's execution ---
SCRIPT_LOG_PATH = os.path.join(ROOT_DIR, 'logs', 'verify_dataset.log') 


# --- NEW PREAMBLE: For SQL-to-NL Translation ---
# This preamble tells the LLM the schema so it can understand the SQL query's intent.
SQL_TO_NL_PREAMBLE = """
You are an expert SQL database analyst. Your task is to translate a given SQL query into a simple, natural language question that a user might have asked to get this SQL.

Use the database schema below for context:

SCHEMA:
1.  'Matches': Info about each match ('match_id', 'season', 'venue', 'city', 'team1', 'team2', 'result_type', 'match_winner', 'player_of_match_id' FK).
2.  'Deliveries': Ball-by-ball data ('delivery_id' PK, 'match_id' FK, player IDs FKs, 'runs_scored', 'extra_runs', 'wicket_type', 'over_number', 'ball_number').
3.  'Players': Central table ('player_id' TEXT PK, 'player_name' TEXT).
4.  'PlayerInMatch': Links 'match_id' FK to 'player_id' FK and 'team_name'.
5.  'FielderDismissals': Links dismissals to fielders ('delivery_id' FK, 'fielder_id' FK).

Respond with *only* the natural language question. Do not explain the SQL or your reasoning.
"""

# --- Pydantic model for the SQL-to-NL LLM's structured output ---
class GeneratedQuestion(BaseModel):
    """The natural language question generated from the SQL query."""
    generated_question: str = Field(..., description="The simple, natural language version of the SQL query.")


# --- Helper Function for logging the comparison ---
def log_to_verification_file(file_path, original_q, sql_q, generated_q):
    """Appends the three-part comparison to the output file."""
    try:
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write("---\n")
            f.write(f"Original Question:\n{original_q}\n\n")
            f.write(f"SQL Query:\n{sql_q}\n\n")
            f.write(f"Generated Question (for verification):\n{generated_q}\n")
    except IOError as e:
        print(f"Error writing to verification file {file_path}: {e}")
        logging.error(f"File logging error: {e}")

# --- Main Logic ---
def main():
    """Reads gold_dataset.json, generates round-trip questions, and saves for review."""
    logging.basicConfig(filename=SCRIPT_LOG_PATH,
                        level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        filemode='w')
    logging.info("Starting verification script.")

    # --- File Check ---
    if not os.path.exists(GOLD_DATASET_PATH):
        print(f"Error: Gold dataset not found at '{GOLD_DATASET_PATH}'.")
        logging.error(f"Gold dataset not found at '{GOLD_DATASET_PATH}'.")
        return

    # --- Initialize LLM ---
    try:
        # We use a slight temperature to make the generated NL questions more natural
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2)
        logging.info("LLM connection initialized.")
    except Exception as e:
        print(f"Error initializing LangChain/LLM components: {e}")
        logging.error(f"LLM/LangChain Initialization Error: {e}")
        return

    # --- Setup SQL-to-NL Chain ---
    sql_to_nl_prompt = ChatPromptTemplate.from_template(
        SQL_TO_NL_PREAMBLE + "\n\nSQL Query:\n{sql_query}"
    )
    sql_to_nl_chain = create_structured_output_runnable(GeneratedQuestion, llm, sql_to_nl_prompt)

    # --- Load Gold Dataset ---
    try:
        with open(GOLD_DATASET_PATH, 'r', encoding='utf-8') as f:
            gold_data = json.load(f)
        print(f"Loaded {len(gold_data)} verified seed queries from {GOLD_DATASET_PATH}.")
        logging.info(f"Loaded {len(gold_data)} seed queries.")
    except Exception as e:
        print(f"Error reading or parsing {GOLD_DATASET_PATH}: {e}")
        logging.error(f"Error reading or parsing {GOLD_DATASET_PATH}: {e}")
        return

    # --- Initialize Output File ---
    try:
        with open(VERIFICATION_OUTPUT_PATH, 'w', encoding='utf-8') as f:
            f.write(f"# Round-Trip Verification Log\n# Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Compare 'Original Question' with 'Generated Question' to verify SQL correctness.\n")
        print(f"Initialized verification output file: {VERIFICATION_OUTPUT_PATH}")
    except IOError as e:
         print(f"Error clearing/creating output file {VERIFICATION_OUTPUT_PATH}: {e}")
         logging.error(f"Error initializing output file: {e}")
         return

    # --- Main Loop ---
    successful_verifications = 0
    failed_verifications = 0

    for idx, entry in enumerate(gold_data, start=1):
        original_question = entry.get('question', 'MISSING_QUESTION')
        sql_query = entry.get('query', 'MISSING_QUERY')
        
        print(f"\n🔄 Verifying Triplet {idx}/{len(gold_data)}: {original_question[:100]}...")
        
        if sql_query == 'MISSING_QUERY' or "ERROR" in sql_query:
            print("   ...Skipping triplet due to invalid SQL.")
            failed_verifications += 1
            log_to_verification_file(VERIFICATION_OUTPUT_PATH, original_question, sql_query, "SKIPPED - SQL WAS INVALID")
            continue
            
        generated_question = "ERROR: LLM call failed" # Default
        try:
            # Step 1: Run SQL-to-NL Chain
            result = sql_to_nl_chain.invoke({"sql_query": sql_query})
            generated_question = result.generated_question
            print("   ✅ Round-trip generation successful.")
            successful_verifications += 1

        except Exception as e:
            error_message = f"Failed processing SQL for question {idx}: {e}"
            print(f"   ❌ ERROR: {error_message}")
            logging.error(error_message)
            generated_question = f"GENERATION ERROR: {e}"
            failed_verifications += 1
        
        finally:
            # Step 2: Log all parts for manual review
            log_to_verification_file(VERIFICATION_OUTPUT_PATH, original_question, sql_query, generated_question)
            # time.sleep(1) # Optional delay to respect API rate limits

    # --- Final Summary ---
    print(f"\n🏁 Round-Trip Verification Complete!")
    print(f"   Successfully generated {successful_verifications} new questions.")
    print(f"   Failed to generate {failed_verifications} new questions.")
    print(f"   Verification data saved to: {VERIFICATION_OUTPUT_PATH}")
    print(f"   Detailed logs saved to: {SCRIPT_LOG_PATH}")
    logging.info("Finished verification script.")


if __name__ == "__main__":
    main()