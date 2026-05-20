"""Initialize MongoDB collections, indexes, and default provider data."""
from __future__ import annotations

import os

import pymongo
from dotenv import load_dotenv

load_dotenv()


def get_mongodb_uri() -> str:
    return os.getenv("MONGODB_URI", "mongodb://localhost:27017")


def get_mongodb_db() -> str:
    return os.getenv("MONGODB_DB", "ServicesAgentDB")


PROVIDERS = [
    {"id": 1, "name": "Ali AC Services", "service_type": "AC Technician", "location": "G-13", "rating": 4.8, "base_price": 1500.0, "available": True},
    {"id": 2, "name": "Zain AC Repair", "service_type": "AC Technician", "location": "G-13", "rating": 4.2, "base_price": 1200.0, "available": True},
    {"id": 3, "name": "Bilal Cooling", "service_type": "AC Technician", "location": "F-8", "rating": 4.6, "base_price": 1800.0, "available": True},
    {"id": 4, "name": "Hassan Plumbers", "service_type": "Plumber", "location": "G-13", "rating": 4.5, "base_price": 1000.0, "available": True},
    {"id": 5, "name": "Tariq Plumb Solutions", "service_type": "Plumber", "location": "G-10", "rating": 4.0, "base_price": 800.0, "available": True},
    {"id": 6, "name": "Raza Electricians", "service_type": "Electrician", "location": "G-13", "rating": 4.7, "base_price": 1200.0, "available": True},
]


def setup_indexes(db) -> None:
    db.users.create_index("email", unique=True)
    db.users.create_index("verification_token")
    db.users.create_index("reset_token")
    try:
        db.token_blacklist.drop_index("expires_at_1")
    except Exception:
        pass
    db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
    db.token_blacklist.create_index("token", unique=True)
    db.threads.create_index("thread_id", unique=True)
    db.threads.create_index([("user_id", 1), ("created_at", -1)])
    db.providers.create_index("id", unique=True)
    db.bookings.create_index("id", unique=True)
    db.bookings.create_index([("provider_id", 1), ("user_id", 1), ("booking_time", 1), ("status", 1)])


def setup_db() -> None:
    mongo_uri = get_mongodb_uri()
    mongo_db_name = get_mongodb_db()
    client = pymongo.MongoClient(mongo_uri)
    db = client[mongo_db_name]

    setup_indexes(db)

    if db.providers.count_documents({}) == 0:
        db.providers.insert_many(PROVIDERS)
        print("MongoDB providers collection populated with default providers.")
    else:
        print("MongoDB providers collection already populated.")

    max_booking = db.bookings.find_one(sort=[("id", -1)])
    db.counters.update_one(
        {"_id": "bookings"},
        {"$max": {"seq": int(max_booking["id"]) if max_booking and max_booking.get("id") is not None else 0}},
        upsert=True,
    )

    client.close()
    print(f"MongoDB setup completed for database: {mongo_db_name}")


if __name__ == "__main__":
    setup_db()
