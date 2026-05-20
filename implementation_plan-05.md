# Implementation Plan: Migrate from SQLite to MongoDB

This document outlines the detailed architecture, database design decisions, and step-by-step changes required to migrate both the application data (from `service_agent.db`) and the LangGraph conversation checkpoint history (from `checkpoints.sqlite`) to MongoDB.

---

## Goal Description

Currently, the application uses two local SQLite databases:
1. `service_agent.db`: Stores application-specific tables: `providers`, `bookings`, `threads`, `users`, and `token_blacklist`.
2. `checkpoints.sqlite`: Stores LangGraph conversation state via `AsyncSqliteSaver`.

We will migrate all data storage to MongoDB. The database connection URL and database name are already set in `.env` as `MONGODB_URI` and `MONGODB_DB`. Since the MongoDB database is not yet initialized or populated, we will:
1. Add necessary Python packages (`pymongo`, `motor`, `langgraph-checkpoint-mongodb`).
2. Update config management to load MongoDB environment variables.
3. Centralize and rewrite all database CRUD operations in `src/db.py` using the asynchronous driver `motor`.
4. Refactor direct `aiosqlite` calls in the agent files (`booking_agent.py`, `discovery_agent.py`, `intent_agent.py`) to use `src/db.py` helper functions, separating concerns.
5. Create a robust one-time migration script (`migrate_sqlite_to_mongo.py`) to read existing SQLite data and safely insert it into MongoDB collections.
6. Replace `AsyncSqliteSaver` in `src/main.py` with `AsyncMongoDBSaver` for asynchronous conversation checkpoints.
7. Adapt the test suites to run against a test database in MongoDB (`ServicesaAgentDB_test`), ensuring full test coverage and clean test execution.

---

## Design Decisions & Tradeoffs

1. **Keep Compatible IDs:** In SQLite, auto-increment integer IDs were used for `providers` (1, 2, 3, etc.) and `bookings`. To avoid breaking other logic and test suites, we will maintain these integer `id` fields in MongoDB alongside standard MongoDB `_id` fields.
2. **Centralized Data Access:** We will rewrite the agents to call async functions in `src/db.py` instead of executing raw database queries directly. This improves separation of concerns and makes changing database engines in the future trivial.
3. **LangGraph Checkpoint Migration Tradeoff:** Checkpoints in `checkpoints.sqlite` are stored in custom SQLite binary formats native to `AsyncSqliteSaver`. LangGraph's `AsyncMongoDBSaver` uses a different document format. Attempting to parse and translate binary blobs between savers is highly complex and error-prone. Therefore, we will:
   - Reset active conversation state history, requiring active threads to start a new turn.
   - Migrate the list of threads (`threads` collection) so users still see their conversation history in `list_user_threads`, but invoking the graph on a thread ID starts fresh in MongoDB. This is the safest, most standard practice for dev-to-prod database migrations.

---

## Proposed Changes

### 1. Dependencies

#### [MODIFY] [pyproject.toml](file:///c:/Users/User-1/Music/informalServicesMPAgent/pyproject.toml)
Add MongoDB libraries to dependencies:
* `pymongo>=4.6.0` (Core synchronous MongoDB driver used by PyMongo checkpointer)
* `motor>=3.3.0` (Asynchronous driver wrapping pymongo for asyncio/FastAPI)
* `langgraph-checkpoint-mongodb>=0.1.0` (Official MongoDB checkpointer for LangGraph)
Remove `langgraph-checkpoint-sqlite` to keep dependencies clean.

---

### 2. Configuration

#### [MODIFY] [src/config.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/config.py)
* Add functions to read environment variables:
  * `get_mongodb_uri() -> str`: Returns `MONGODB_URI` from `.env`, defaulting to `"mongodb://localhost:27017"`.
  * `get_mongodb_db() -> str`: Returns `MONGODB_DB` from `.env`, defaulting to `"ServicesAgentDB"`.

---

### 3. Database Layer

#### [MODIFY] [src/db.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/db.py)
Complete overhaul to use `motor.motor_asyncio.AsyncIOMotorClient`:
* Establish a single, shared, async client connection to MongoDB.
* Provide an initialization helper `init_mongodb(uri, db_name)` to be called during FastAPI startup lifespan.
* Create required indexes at startup:
  * `users`: Unique index on `email`, normal index on `verification_token`, `reset_token`
  * `token_blacklist`: Normal index on `expires_at`
* Port all database operations to Mongo syntax:
  * `get_user_by_email`
  * `create_user`
  * `verify_user_email`
  * `update_verification_token`
  * `set_reset_token`
  * `reset_user_password`
  * `blacklist_token`
  * `is_token_blacklisted`
  * `save_thread`
  * `update_thread_title`
  * `get_threads`
  * `get_bookings`
* Implement new consolidated database methods (previously run directly in agents using sqlite):
  * `check_provider_availability(provider_id: int) -> bool`
  * `find_confirmed_booking(provider_id: int, user_id: str, booking_time: str) -> dict | None`
  * `create_booking(provider_id: int, user_id: str, booking_time: str, status: str) -> str` (returns the new booking's ID)
  * `get_active_providers() -> list[dict]`
  * `get_distinct_service_types() -> list[str]`

---

### 4. Setup and Dummy Data

#### [MODIFY] [db_setup.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/db_setup.py)
Adapt the script to connect to MongoDB synchronously via `pymongo`:
* Create `providers` collection and seed with default providers dummy data if empty.
* Setup standard indexes for `users` and `token_blacklist` collections.

---

### 5. Agents Refactoring

#### [MODIFY] [src/agents/booking_agent.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/agents/booking_agent.py)
* Replace direct `aiosqlite` imports and connections in `simulate_booking` with calls to:
  * `check_provider_availability`
  * `find_confirmed_booking`
  * `create_booking`

#### [MODIFY] [src/agents/discovery_agent.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/agents/discovery_agent.py)
* Replace direct `aiosqlite` connection in `discover_providers` with `get_active_providers()` from `src/db.py`.

#### [MODIFY] [src/agents/intent_agent.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/agents/intent_agent.py)
* Replace direct `aiosqlite` connection in `load_valid_services` with `get_distinct_service_types()` from `src/db.py`.

---

### 6. App Life Cycle & Checkpointer

#### [MODIFY] [src/main.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/main.py)
* Remove `aiosqlite` and `AsyncSqliteSaver` imports.
* Import `AsyncMongoDBSaver` from `langgraph.checkpoint.mongodb.aio`.
* Update `@asynccontextmanager async def lifespan(app: FastAPI)`:
  * Fetch MongoDB URI and DB name from `src.config`.
  * Call `init_mongodb(uri, db_name)` to set up the shared database client and run any schema validation.
  * Initialize `AsyncMongoDBSaver.from_conn_string(uri)` as checkpointer.
  * Compile LangGraph with the new checkpointer.
  * Update thread authorization checks to query MongoDB instead of SQLite.

---

### 7. Migration Script

#### [NEW] [migrate_sqlite_to_mongo.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/migrate_sqlite_to_mongo.py)
Create a standalone CLI script to run the migration:
* Check for presence of SQLite databases (`service_agent.db`).
* Read all rows from `providers`, `bookings`, `threads`, `users`, and `token_blacklist` using standard sqlite3 driver.
* Connect to MongoDB and bulk insert them into matching collections.
* Provide clear summary console output of successfully migrated records.

---

### 8. Testing Adaptation

#### [MODIFY] [tests/test_auth.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/tests/test_auth.py)
* Update test configurations to use a temporary MongoDB test database (e.g. `ServicesAgentDB_test`).
* Clean up/drop the test database collections in `setUp` and `tearDown` using `pymongo`.

#### [MODIFY] [tests/test_reliability_workflow.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/tests/test_reliability_workflow.py)
* Update test setup to use `ServicesAgentDB_test` and `AsyncMongoDBSaver`.
* Populate test providers data directly into the test database.
* Drop test collections in cleanup.

---

## Verification Plan

### Automated Tests
1. **Database Migration Script Validation:**
   Run the migration script to verify existing Sqlite database is successfully moved to MongoDB:
   ```powershell
   python migrate_sqlite_to_mongo.py
   ```
2. **Execute Existing Test Suites:**
   Verify all business rules, endpoints, and authentication workflows pass perfectly:
   ```powershell
   pytest tests/
   ```
3. **Execute SSE Integration Verification Script:**
   Confirm thread title generation, continuations, streaming event formats, and auth are functioning on MongoDB:
   ```powershell
   python verify_sse_threads.py
   ```

### Manual Verification
1. Run `python db_setup.py` to confirm MongoDB collections and indexes are initialized correctly if no database existed.
2. Inspect the collections using MongoDB Compass or shell commands to verify document structure and database states.
