import sqlite3

def setup_db():
    conn = sqlite3.connect("service_agent.db")
    cursor = conn.cursor()

    # Create providers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        service_type TEXT,
        location TEXT,
        rating REAL,
        base_price REAL,
        available BOOLEAN
    )
    """)

    # Create bookings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER,
        user_id TEXT,
        booking_time TEXT,
        status TEXT,
        FOREIGN KEY (provider_id) REFERENCES providers (id)
    )
    """)

    # Create threads table (links thread_id to user + title)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS threads (
        thread_id TEXT PRIMARY KEY,
        user_id   TEXT NOT NULL,
        title     TEXT NOT NULL DEFAULT 'New Conversation',
        created_at TEXT NOT NULL
    )
    """)

    # Create users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL DEFAULT '',
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_verified INTEGER DEFAULT 0,
        verification_token TEXT,
        verification_expires_at TEXT,
        reset_token TEXT,
        reset_expires_at TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cursor.fetchall()}
    if "name" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    if "verification_expires_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN verification_expires_at TEXT")
    if "reset_expires_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN reset_expires_at TEXT")

    # Create token_blacklist table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS token_blacklist (
        token TEXT PRIMARY KEY,
        expires_at TEXT NOT NULL
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_verification_token ON users (verification_token)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users (reset_token)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_blacklist_expires_at ON token_blacklist (expires_at)")
    conn.commit()

    # Check if providers are already populated
    cursor.execute("SELECT COUNT(*) FROM providers")
    count = cursor.fetchone()[0]

    if count == 0:
        # Dummy data
        providers_data = [
            ("Ali AC Services", "AC Technician", "G-13", 4.8, 1500, True),
            ("Zain AC Repair", "AC Technician", "G-13", 4.2, 1200, True),
            ("Bilal Cooling", "AC Technician", "F-8", 4.6, 1800, True),
            ("Hassan Plumbers", "Plumber", "G-13", 4.5, 1000, True),
            ("Tariq Plumb Solutions", "Plumber", "G-10", 4.0, 800, True),
            ("Raza Electricians", "Electrician", "G-13", 4.7, 1200, True)
        ]
        
        cursor.executemany("""
        INSERT INTO providers (name, service_type, location, rating, base_price, available)
        VALUES (?, ?, ?, ?, ?, ?)
        """, providers_data)
        
        conn.commit()
        print("Database initialized and populated with dummy providers.")
    else:
        print("Database already populated.")

    conn.close()

if __name__ == "__main__":
    setup_db()
