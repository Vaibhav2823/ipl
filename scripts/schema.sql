PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS Players (
    player_id TEXT PRIMARY KEY,
    player_name TEXT NOT NULL -- UNIQUE constraint removed
);

CREATE TABLE IF NOT EXISTS Matches (
    match_id INTEGER PRIMARY KEY,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    venue TEXT NOT NULL,
    city TEXT,
    stage TEXT DEFAULT 'Group',
    team1 TEXT NOT NULL,
    team2 TEXT NOT NULL,
    toss_winner TEXT NOT NULL,
    toss_decision TEXT NOT NULL,
    match_winner TEXT,
    result_type TEXT,
    result_margin INTEGER,
    player_of_match_id TEXT,
    umpire1 TEXT,
    umpire2 TEXT,
    FOREIGN KEY (player_of_match_id) REFERENCES Players (player_id)
);

CREATE TABLE IF NOT EXISTS Deliveries (
    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    inning INTEGER NOT NULL,
    over_number INTEGER NOT NULL,
    ball_number INTEGER NOT NULL, -- This will store the legal ball number (1-6)
    batting_team TEXT NOT NULL,
    bowling_team TEXT NOT NULL,
    striker_id TEXT NOT NULL,
    non_striker_id TEXT NOT NULL,
    bowler_id TEXT NOT NULL,
    runs_scored INTEGER NOT NULL, -- Runs off bat
    extra_runs INTEGER NOT NULL, -- Total extras this ball
    
    -- NEW COLUMNS FOR DETAILED EXTRAS --
    wides INTEGER DEFAULT 0,
    noballs INTEGER DEFAULT 0,
    byes INTEGER DEFAULT 0,
    legbyes INTEGER DEFAULT 0,
    -- END NEW COLUMNS --
    
    wicket_type TEXT,
    player_out_id TEXT,
    FOREIGN KEY (match_id) REFERENCES Matches (match_id),
    FOREIGN KEY (striker_id) REFERENCES Players (player_id),
    FOREIGN KEY (non_striker_id) REFERENCES Players (player_id),
    FOREIGN KEY (bowler_id) REFERENCES Players (player_id),
    FOREIGN KEY (player_out_id) REFERENCES Players (player_id)
);

CREATE TABLE IF NOT EXISTS PlayerInMatch (
    match_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    team_name TEXT NOT NULL,
    PRIMARY KEY (match_id, player_id),
    FOREIGN KEY (match_id) REFERENCES Matches(match_id),
    FOREIGN KEY (player_id) REFERENCES Players(player_id)
);

CREATE TABLE IF NOT EXISTS FielderDismissals (
    fielder_dismissal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id INTEGER NOT NULL,
    fielder_id TEXT NOT NULL,
    FOREIGN KEY (delivery_id) REFERENCES Deliveries(delivery_id),
    FOREIGN KEY (fielder_id) REFERENCES Players(player_id)
);

PRAGMA foreign_keys=ON;