import os
import json
import sqlite3
import logging
import time

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DB_PATH = os.path.join(ROOT_DIR, 'data', 'processed', 'ipl.db')
RAW_DATA_DIR = os.path.join(ROOT_DIR, 'data', 'raw', 'ipl_json')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')
LOG_PATH = os.path.join(ROOT_DIR, 'logs', 'ingestion.log')

# --- Set up Logging ---
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s', filemode='w')

def create_database():
    """Reads schema.sql and creates the database tables."""
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        print(f"Creating database at {DB_PATH}...")
        with open(SCHEMA_PATH, 'r') as f:
            schema = f.read()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.executescript(schema)
        conn.commit()
        conn.close()
        print("Database and tables created successfully.")
    except Exception as e:
        logging.error(f"DATABASE CREATION FAILED: {e}")
        print(f"DATABASE CREATION FAILED. Check {LOG_PATH} for details.")
        exit()

def process_file(db_conn, file_path):
    """Processes a single JSON file and inserts its data into the DB."""
    cursor = db_conn.cursor()
    filename = os.path.basename(file_path)
    match_id = int(filename.split('.')[0])
    logging.info(f"--- Start processing file: {filename} ---")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        info = data.get('info', {})
        player_registry_raw = info.get('registry', {}).get('people', {})
        if not player_registry_raw:
             logging.warning(f"No 'info.registry.people' found in {filename}. Skipping file.")
             raise ValueError("Missing player registry in file")

        file_player_registry = {
            name.strip(): pid
            for name, pid in player_registry_raw.items()
            if name and isinstance(name, str) and pid and isinstance(pid, str)
        }

        if file_player_registry:
            players_data = [(pid, name) for name, pid in file_player_registry.items()]
            cursor.executemany("INSERT OR IGNORE INTO Players (player_id, player_name) VALUES (?, ?)", players_data)

        def get_player_id(common_name):
            if not common_name or not isinstance(common_name, str): return None
            pid = file_player_registry.get(common_name.strip())
            return pid

        # 1. Insert into Matches table
        pom_name_common = info.get('player_of_match', [None])[0]
        pom_id = get_player_id(pom_name_common) if pom_name_common else None
        outcome = info.get('outcome', {})
        winner = outcome.get('winner')
        result_type = list(outcome.get('by', {}).keys())[0] if outcome.get('by') else info.get('outcome',{}).get('result', 'no result')
        margin = list(outcome.get('by', {}).values())[0] if outcome.get('by') else None
        stage = info.get('event', {}).get('stage', 'Group')

        match_data = (
            match_id, str(info.get('season', 'Unknown')), info.get('dates', [''])[0],
            info.get('venue', 'Unknown'), info.get('city'), stage,
            info.get('teams', ['',''])[0], info.get('teams', ['',''])[1],
            info.get('toss', {}).get('winner', 'Unknown'), info.get('toss', {}).get('decision', 'Unknown'),
            winner, result_type, margin, pom_id,
            info.get('officials', {}).get('umpires', [None, None])[0],
            info.get('officials', {}).get('umpires', [None, None])[1]
        )
        cursor.execute("""
            INSERT INTO Matches (match_id, season, match_date, venue, city, stage, team1, team2,
            toss_winner, toss_decision, match_winner, result_type, result_margin,
            player_of_match_id, umpire1, umpire2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, match_data)

        # 2. Insert into PlayerInMatch table
        playing_xi_data = []
        players_info = info.get('players', {})
        for team_name, player_list in players_info.items():
            for common_name in player_list:
                player_id = get_player_id(common_name)
                if player_id:
                    playing_xi_data.append((match_id, player_id, team_name))
                else:
                     if common_name.strip() not in file_player_registry and common_name.strip():
                        logging.warning(f"Player '{common_name}' from XI in {filename} not in registry. Skipping PlayerInMatch.")
        if playing_xi_data:
             cursor.executemany("""
                 INSERT OR IGNORE INTO PlayerInMatch (match_id, player_id, team_name) VALUES (?, ?, ?)
             """, playing_xi_data)

        # 3. Insert into Deliveries and FielderDismissals tables
        for i, inning_data in enumerate(data.get('innings', [])):
            inning_number = i + 1
            if inning_data.get("super_over"):
                inning_number += 2

            batting_team = inning_data.get('team')
            teams = info.get('teams', [])
            bowling_team = teams[1] if len(teams) > 1 and teams[0] == batting_team else (teams[0] if teams else 'Unknown')

            for over_data in inning_data.get('overs', []):
                over_num = over_data.get('over')
                legal_ball_count_in_over = 0

                for delivery_index, delivery in enumerate(over_data.get('deliveries', [])):
                    
                    # --- MODIFIED: Extract detailed extras ---
                    extras_info = delivery.get('extras', {})
                    wides = extras_info.get('wides', 0)
                    noballs = extras_info.get('noballs', 0)
                    byes = extras_info.get('byes', 0)
                    legbyes = extras_info.get('legbyes', 0)
                    
                    # --- LEGAL BALL COUNT LOGIC ---
                    is_legal_delivery = (wides == 0 and noballs == 0)
                    if is_legal_delivery:
                        legal_ball_count_in_over += 1
                    ball_number_to_store = legal_ball_count_in_over
                    # --- END LEGAL BALL LOGIC ---

                    striker_name = delivery.get('batter')
                    non_striker_name = delivery.get('non_striker')
                    bowler_name = delivery.get('bowler')

                    striker_id = get_player_id(striker_name)
                    non_striker_id = get_player_id(non_striker_name)
                    bowler_id = get_player_id(bowler_name)

                    if not all([striker_id, non_striker_id, bowler_id]):
                        missing_detail = []
                        if striker_name and not striker_id: missing_detail.append(f"Striker:'{striker_name}'")
                        if non_striker_name and not non_striker_id: missing_detail.append(f"NonStriker:'{non_striker_name}'")
                        if bowler_name and not bowler_id: missing_detail.append(f"Bowler:'{bowler_name}'")
                        logging.warning(f"Skipping delivery in {filename} (O:{over_num}, SeqBall:{delivery_index+1}) due to missing ID lookup for: {', '.join(missing_detail)}.")
                        continue

                    wicket_info_list = delivery.get('wickets')
                    wicket_info = wicket_info_list[0] if wicket_info_list else {}
                    player_out_name = wicket_info.get('player_out')
                    player_out_id = get_player_id(player_out_name) if player_out_name else None
                    fielder_names = [f.get('name') for f in wicket_info.get('fielders', []) if f.get('name')]
                    fielder_ids = [get_player_id(name) for name in fielder_names if get_player_id(name)]

                    if player_out_name and not player_out_id:
                         logging.warning(f"Player out '{player_out_name}' in {filename} (O:{over_num}, B:{ball_number_to_store}) ID lookup failed. player_out_id=NULL.")
                    if fielder_names and len(fielder_names) != len(fielder_ids):
                         failed_lookups = [name for name in fielder_names if not get_player_id(name)]
                         logging.warning(f"Some fielder ID lookups failed for {failed_lookups} in {filename} (O:{over_num}, B:{ball_number_to_store}).")

                    # --- MODIFIED: Add new extra columns to insertion data ---
                    delivery_row_data = (
                        match_id, inning_number, over_num,
                        ball_number_to_store, # Use the calculated legal ball number
                        batting_team, bowling_team,
                        striker_id, non_striker_id, bowler_id,
                        delivery.get('runs', {}).get('batter', 0),
                        delivery.get('runs', {}).get('extras', 0), # Total extras
                        wides, noballs, byes, legbyes, # Detailed extras
                        wicket_info.get('kind'), player_out_id
                    )
                    
                    try:
                        # --- MODIFIED: Updated INSERT statement ---
                        cursor.execute("""
                            INSERT INTO Deliveries (
                                match_id, inning, over_number, ball_number, batting_team,
                                bowling_team, striker_id, non_striker_id, bowler_id,
                                runs_scored, extra_runs, 
                                wides, noballs, byes, legbyes, -- New columns
                                wicket_type, player_out_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, delivery_row_data)
                        
                        current_delivery_id = cursor.lastrowid
                        
                        if fielder_ids:
                            fielder_data_for_insert = [(current_delivery_id, f_id) for f_id in fielder_ids]
                            cursor.executemany("""
                                INSERT INTO FielderDismissals (delivery_id, fielder_id) VALUES (?, ?)
                            """, fielder_data_for_insert)

                    except sqlite3.IntegrityError as e:
                        logging.error(f"IntegrityError inserting delivery/fielder in {filename} (O:{over_num}, B:{ball_number_to_store}): {e}. Skipping delivery.")
                        continue

    except Exception as e:
        logging.error(f"Failed processing {filename}: {e}")
        raise

def main():
    """Main function to orchestrate the database creation and ingestion."""
    create_database()
    files_to_process = [f for f in os.listdir(RAW_DATA_DIR) if f.endswith('.json')]
    total_files = len(files_to_process)
    print(f"Found {total_files} JSON files to process.")

    db_conn = sqlite3.connect(DB_PATH)
    db_conn.execute("PRAGMA foreign_keys = ON;")

    processed_count = 0
    skipped_count = 0
    files_to_process.sort(key=lambda x: int(x.split('.')[0]))

    for i, filename in enumerate(files_to_process):
        # --- MODIFIED: Added check for void match ---
        if filename == '1473495.json':
            print(f"\nSkipping void match file: {filename} (File {i+1}/{total_files})")
            logging.info(f"Skipping void match file: {filename}")
            skipped_count += 1
            continue
        # --- END MODIFICATION ---

        print(f"\rProcessing file {i+1}/{total_files}: {filename} (Skipped: {skipped_count})", end="")
        file_path = os.path.join(RAW_DATA_DIR, filename)

        try:
            with db_conn:
                 process_file(db_conn, file_path)
            processed_count += 1
        except Exception as e:
             print(f"\nERROR processing {filename}: {e}. Skipping file.")
             if not isinstance(e, sqlite3.Error):
                 logging.error(f"UNEXPECTED high-level ERROR processing {filename}: {e}.")
             skipped_count += 1

    db_conn.close()
    print(f"\n\nIngestion complete!")
    print(f"Successfully processed: {processed_count}/{total_files} files.")
    print(f"Skipped due to errors or exclusion: {skipped_count} files.")
    print(f"Database 'ipl.db' is ready with detailed extras data.")
    print(f"Check '{LOG_PATH}' for warnings and error details.")

if __name__ == "__main__":
    main()