"""Async helpers for reading/writing app-level data."""
import aiosqlite
from datetime import datetime, timezone

from src.agent_utils import assistant_messages
from src.config import get_db_path


REQUIRED_TABLES = {"providers", "bookings", "threads", "users", "token_blacklist"}


async def migrate_database_schema() -> None:
    """Apply small compatible schema migrations for existing SQLite databases."""
    async with aiosqlite.connect(get_db_path()) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {row[0] for row in await cursor.fetchall()}
        if not {"users", "token_blacklist"}.issubset(tables):
            return

        cursor = await conn.execute("PRAGMA table_info(users)")
        user_columns = {row[1] for row in await cursor.fetchall()}
        if "name" not in user_columns:
            await conn.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "verification_expires_at" not in user_columns:
            await conn.execute("ALTER TABLE users ADD COLUMN verification_expires_at TEXT")
        if "reset_expires_at" not in user_columns:
            await conn.execute("ALTER TABLE users ADD COLUMN reset_expires_at TEXT")

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_verification_token ON users (verification_token)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users (reset_token)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_token_blacklist_expires_at ON token_blacklist (expires_at)")
        await conn.commit()


async def validate_database() -> list[str]:
    """Return startup warnings for missing tables or seed data."""
    warnings = []
    async with aiosqlite.connect(get_db_path()) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {r[0] for r in await cursor.fetchall()}
        missing = REQUIRED_TABLES - tables
        if missing:
            warnings.append(f"Missing database tables: {', '.join(sorted(missing))}")
            return warnings

        cursor = await conn.execute("SELECT COUNT(*) FROM providers")
        provider_count = (await cursor.fetchone())[0]
        if provider_count == 0:
            warnings.append("No providers are configured")
    return warnings


async def thread_exists(thread_id: str) -> bool:
    async with aiosqlite.connect(get_db_path()) as conn:
        cur = await conn.execute("SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,))
        return await cur.fetchone() is not None


async def save_thread(thread_id: str, user_id: str, title: str = "New Conversation") -> None:
    """Insert a new thread row. Silently no-ops if thread_id already exists."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO threads (thread_id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, user_id, title, created_at),
        )
        await conn.commit()


async def update_thread_title(thread_id: str, title: str) -> None:
    """Update the title of an existing thread (called from background task)."""
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "UPDATE threads SET title = ? WHERE thread_id = ?",
            (title, thread_id),
        )
        await conn.commit()


async def get_threads(user_id: str) -> list[dict]:
    """Return all threads for a user, newest first."""
    async with aiosqlite.connect(get_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT thread_id, title, created_at FROM threads WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_messages(thread_id: str, graph) -> list[dict]:
    """
    Read the LangGraph checkpoint state for the thread and return
    the messages list filtered to user + assistant roles only.
    """
    config = {"configurable": {"thread_id": thread_id}}
    state_snap = await graph.aget_state(config)
    if not state_snap or not getattr(state_snap, "values", None):
        return []
    return assistant_messages(state_snap.values.get("messages", []))


async def get_bookings(user_id: str) -> list[dict]:
    """Return bookings for a user joined with provider details, newest first."""
    async with aiosqlite.connect(get_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT
                b.id,
                p.name   AS provider_name,
                p.service_type,
                b.booking_time,
                b.status
            FROM bookings b
            JOIN providers p ON p.id = b.provider_id
            WHERE b.user_id = ?
            ORDER BY b.id DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(get_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(name: str, email: str, password_hash: str, verification_token: str, verification_expires_at: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO users (name, email, password_hash, verification_token, verification_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name.strip(), email.strip().lower(), password_hash, verification_token, verification_expires_at, created_at),
        )
        await conn.commit()


async def verify_user_email(token: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(get_db_path()) as conn:
        cursor = await conn.execute(
            """
            SELECT 1 FROM users
            WHERE verification_token = ?
              AND (verification_expires_at IS NULL OR verification_expires_at > ?)
            """,
            (token, now),
        )
        if await cursor.fetchone() is None:
            return False

        await conn.execute(
            """
            UPDATE users
            SET is_verified = 1, verification_token = NULL, verification_expires_at = NULL
            WHERE verification_token = ?
            """,
            (token,),
        )
        await conn.commit()
        return True


async def update_verification_token(email: str, token: str, expires_at: str) -> None:
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "UPDATE users SET verification_token = ?, verification_expires_at = ? WHERE email = ?",
            (token, expires_at, email.strip().lower()),
        )
        await conn.commit()


async def set_reset_token(email: str, token: str, expires_at: str) -> None:
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "UPDATE users SET reset_token = ?, reset_expires_at = ? WHERE email = ?",
            (token, expires_at, email.strip().lower()),
        )
        await conn.commit()


async def reset_user_password(token: str, new_password_hash: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(get_db_path()) as conn:
        cursor = await conn.execute(
            """
            SELECT 1 FROM users
            WHERE reset_token = ?
              AND (reset_expires_at IS NULL OR reset_expires_at > ?)
            """,
            (token, now),
        )
        if await cursor.fetchone() is None:
            return False

        await conn.execute(
            """
            UPDATE users
            SET password_hash = ?, reset_token = NULL, reset_expires_at = NULL
            WHERE reset_token = ?
            """,
            (new_password_hash, token),
        )
        await conn.commit()
        return True


async def blacklist_token(token: str, expires_at: str) -> None:
    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO token_blacklist (token, expires_at) VALUES (?, ?)",
            (token, expires_at),
        )
        await conn.commit()


async def is_token_blacklisted(token: str) -> bool:
    async with aiosqlite.connect(get_db_path()) as conn:
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute("DELETE FROM token_blacklist WHERE expires_at <= ?", (now,))
        await conn.commit()
        cursor = await conn.execute(
            "SELECT 1 FROM token_blacklist WHERE token = ?",
            (token,),
        )
        return await cursor.fetchone() is not None
