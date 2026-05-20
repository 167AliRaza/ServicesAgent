"""Async helpers for reading/writing MongoDB app-level data."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import motor.motor_asyncio

from pymongo import ReturnDocument

from src.agent_utils import assistant_messages
from src.config import get_mongodb_server_selection_timeout_ms

# Globals for Motor connection
db_client = None
db = None
logger = logging.getLogger(__name__)


def _require_db():
    if db is None:
        raise RuntimeError("MongoDB is not initialized")
    return db


def init_mongodb(uri: str, db_name: str) -> None:
    """Initialize the shared Motor client and database objects."""
    global db_client, db
    if db_client is not None:
        db_client.close()
    db_client = motor.motor_asyncio.AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=get_mongodb_server_selection_timeout_ms(),
    )
    db = db_client[db_name]


def close_mongodb() -> None:
    """Close the shared Motor client."""
    global db_client, db
    if db_client is not None:
        db_client.close()
    db_client = None
    db = None


def _normalize_provider_id(val) -> int:
    """Gracefully normalize provider ID to integer if possible."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return val


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            normalized = raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


async def create_mongodb_indexes() -> None:
    """Ensure all required indexes exist in the MongoDB collections."""
    database = _require_db()
    # Users collection indexes
    await database.users.create_index("email", unique=True)
    await database.users.create_index("verification_token")
    await database.users.create_index("reset_token")
    
    # Blacklist collection indexes
    try:
        await database.token_blacklist.drop_index("expires_at_1")
    except Exception:
        pass
    await database.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
    await database.token_blacklist.create_index("token", unique=True)
    await database.threads.create_index("thread_id", unique=True)
    await database.threads.create_index([("user_id", 1), ("created_at", -1)])
    await database.providers.create_index("id", unique=True)
    await database.bookings.create_index("id", unique=True)
    await database.bookings.create_index([("provider_id", 1), ("user_id", 1), ("booking_time", 1), ("status", 1)])


async def migrate_database_schema() -> None:
    """Ensure indexes exist during startup lifecycle (no-op database schema migration)."""
    await create_mongodb_indexes()


async def validate_database() -> list[str]:
    """Return startup warnings for missing collections or seed data."""
    warnings = []
    database = _require_db()

    provider_count = await database.providers.count_documents({})
    if provider_count == 0:
        warnings.append("No providers are configured")
    return warnings


async def thread_exists(thread_id: str) -> bool:
    """Check if a thread ID exists in threads collection."""
    database = _require_db()
    doc = await database.threads.find_one({"thread_id": thread_id})
    return doc is not None


async def get_thread_owner(thread_id: str) -> str | None:
    """Return the owning user ID for a thread, if the thread exists."""
    database = _require_db()
    doc = await database.threads.find_one({"thread_id": thread_id}, {"user_id": 1})
    return doc.get("user_id") if doc else None


async def save_thread(thread_id: str, user_id: str, title: str = "New Conversation") -> None:
    """Insert a new thread. Silently no-ops if thread_id already exists."""
    database = _require_db()
    created_at = _utc_now()
    try:
        await database.threads.update_one(
            {"thread_id": thread_id},
            {"$setOnInsert": {"user_id": user_id, "title": title, "created_at": created_at}},
            upsert=True
        )
    except Exception:
        logger.exception("Failed to save thread %s", thread_id)
        raise


async def update_thread_title(thread_id: str, title: str) -> None:
    """Update the title of an existing thread (called from background task)."""
    database = _require_db()
    await database.threads.update_one(
        {"thread_id": thread_id},
        {"$set": {"title": title}}
    )


async def get_threads(user_id: str) -> list[dict]:
    """Return all threads for a user, newest first."""
    database = _require_db()
    cursor = database.threads.find({"user_id": user_id}).sort("created_at", -1)
    results = []
    async for doc in cursor:
        results.append({
            "thread_id": doc["thread_id"],
            "title": doc.get("title", "New Conversation"),
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")
        })
    return results


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
    database = _require_db()
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$sort": {"id": -1}},  # Sort by integer booking id descending
        {
            "$lookup": {
                "from": "providers",
                "localField": "provider_id",
                "foreignField": "id",
                "as": "provider"
            }
        },
        {"$unwind": {"path": "$provider", "preserveNullAndEmptyArrays": True}}
    ]
    cursor = database.bookings.aggregate(pipeline)
    results = []
    async for doc in cursor:
        provider = doc.get("provider") or {}
        results.append({
            "id": doc.get("id"),
            "provider_name": provider.get("name", "Unknown Provider"),
            "service_type": provider.get("service_type", "Unknown Service"),
            "booking_time": doc.get("booking_time"),
            "status": doc.get("status")
        })
    return results


async def get_user_by_email(email: str) -> dict | None:
    """Fetch user detail dictionary by unique email address."""
    database = _require_db()
    doc = await database.users.find_one({"email": email.strip().lower()})
    if doc:
        user_dict = dict(doc)
        if "_id" in user_dict:
            user_dict["id"] = str(user_dict["_id"])
            del user_dict["_id"]
        return user_dict
    return None


async def create_user(name: str, email: str, password_hash: str, verification_token: str, verification_expires_at: str) -> None:
    """Insert a new user document."""
    database = _require_db()
    created_at = _utc_now()
    await database.users.insert_one({
        "name": name.strip(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "is_verified": 0,
        "verification_token": verification_token,
        "verification_expires_at": _to_datetime(verification_expires_at),
        "created_at": created_at
    })


async def verify_user_email(token: str) -> bool:
    """Verify user by action verification token."""
    database = _require_db()
    now = _utc_now()
    user = await database.users.find_one({
        "verification_token": token,
        "$or": [
            {"verification_expires_at": None},
            {"verification_expires_at": {"$gt": now}}
        ]
    })
    if not user:
        return False

    await database.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "is_verified": 1,
                "verification_token": None,
                "verification_expires_at": None
            }
        }
    )
    return True


async def update_verification_token(email: str, token: str, expires_at: str) -> None:
    """Update verification token for an unverified user email."""
    database = _require_db()
    await database.users.update_one(
        {"email": email.strip().lower()},
        {"$set": {"verification_token": token, "verification_expires_at": _to_datetime(expires_at)}}
    )


async def set_reset_token(email: str, token: str, expires_at: str) -> None:
    """Configure reset token for user password recovery request."""
    database = _require_db()
    await database.users.update_one(
        {"email": email.strip().lower()},
        {"$set": {"reset_token": token, "reset_expires_at": _to_datetime(expires_at)}}
    )


async def reset_user_password(token: str, new_password_hash: str) -> bool:
    """Reset password utilizing valid token."""
    database = _require_db()
    now = _utc_now()
    user = await database.users.find_one({
        "reset_token": token,
        "$or": [
            {"reset_expires_at": None},
            {"reset_expires_at": {"$gt": now}}
        ]
    })
    if not user:
        return False

    await database.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": new_password_hash,
                "reset_token": None,
                "reset_expires_at": None
            }
        }
    )
    return True


async def blacklist_token(token: str, expires_at: str) -> None:
    """Add a logged out JWT token to token_blacklist collection."""
    try:
        database = _require_db()
        await database.token_blacklist.update_one(
            {"token": token},
            {"$setOnInsert": {"expires_at": _to_datetime(expires_at)}},
            upsert=True
        )
    except Exception:
        logger.exception("Failed to blacklist token")
        raise


async def is_token_blacklisted(token: str) -> bool:
    """Clean expired entries and verify if token exists in blacklist."""
    database = _require_db()
    now = _utc_now()
    await database.token_blacklist.delete_many({"expires_at": {"$lte": now}})
    doc = await database.token_blacklist.find_one({"token": token})
    return doc is not None


# Consolidated helper functions for agent logic

async def check_provider_availability(provider_id) -> bool:
    """Verify if a provider is configured and available in database."""
    database = _require_db()
    pid = _normalize_provider_id(provider_id)
    doc = await database.providers.find_one({"id": pid})
    return doc is not None and doc.get("available") is True


async def find_confirmed_booking(provider_id, user_id: str, booking_time: str) -> dict | None:
    """Check if an identical confirmed slot exists for a provider + user + time."""
    database = _require_db()
    pid = _normalize_provider_id(provider_id)
    doc = await database.bookings.find_one({
        "provider_id": pid,
        "user_id": user_id,
        "booking_time": booking_time,
        "status": "CONFIRMED"
    })
    if doc:
        booking_dict = dict(doc)
        if "_id" in booking_dict:
            booking_dict["_id"] = str(booking_dict["_id"])
        return booking_dict
    return None


async def create_booking(provider_id, user_id: str, booking_time: str, status: str) -> int:
    """Create a new booking slot, returning its sequential integer ID."""
    database = _require_db()
    pid = _normalize_provider_id(provider_id)
    counter = await database.counters.find_one_and_update(
        {"_id": "bookings"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    next_id = int(counter["seq"])
    await database.bookings.insert_one({
        "id": next_id,
        "provider_id": pid,
        "user_id": user_id,
        "booking_time": booking_time,
        "status": status
    })
    return next_id


async def get_active_providers() -> list[dict]:
    """Retrieve all available providers in the system."""
    database = _require_db()
    cursor = database.providers.find({"available": True})
    results = []
    async for doc in cursor:
        results.append({
            "id": doc["id"],
            "name": doc["name"],
            "service_type": doc["service_type"],
            "location": doc["location"],
            "rating": doc["rating"],
            "base_price": doc["base_price"]
        })
    return results


async def get_distinct_service_types() -> list[str]:
    """Fetch distinct service types from providers data."""
    database = _require_db()
    types = await database.providers.distinct("service_type")
    return [str(t) for t in types]
