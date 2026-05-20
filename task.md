# Tasks

- [x] **Phase 1: Environment & Mock Data**
  - [x] Initialize Python project using `uv`.
  - [x] Add dependencies: `langgraph`, `google-generativeai`, `pydantic`, `fastapi`, `uvicorn`.
  - [x] Create `db_setup.py` to initialize the SQLite database (`service_agent.db`).
  - [x] Populate SQLite with mock providers (e.g., AC Technicians in G-13, F-8).

- [x] **Phase 2: Core Agents Implementation**
  - [x] Create shared state definitions in `src/state.py`.
  - [x] Implement Intent Extraction Agent (`src/agents/intent_agent.py`).
  - [x] Implement Provider Discovery Agent (`src/agents/discovery_agent.py`).
  - [x] Implement Matching & Ranking Agent (`src/agents/ranking_agent.py`).
  - [x] Implement Action Simulator Agent (`src/agents/booking_agent.py`).
  - [x] Implement Follow-Up Agent (`src/agents/followup_agent.py`).

- [x] **Phase 3: Workflow Orchestration & Interface**
  - [x] Assemble LangGraph pipeline in `src/workflow.py`.
  - [x] Build FastAPI app in `src/main.py`.
  - [x] Add `POST /request-service` endpoint.

- [x] **Phase 4: Verification & Mobile-Ready Upgrades**
  - [x] Start the FastAPI server and warm-start all caches.
  - [x] Send test requests covering conversational multi-turn, Urdu, and Roman Urdu.
  - [x] Verify SQLite booking status updates and asynchronous database drivers.
  - [x] Complete robust rejection handling and CORS for physical Expo mobile devices.
  - [x] Add fully functional frontend integration hook and screen walk-through artifact.

- [x] **Phase 5: Refactoring Endpoints & Agent Output Strategies**
  - [x] Merge `reply` endpoint into `request` endpoint in `src/main.py`
  - [x] Define Pydantic models for structured schema extraction in agents
  - [x] Implement Gemini structured output for Intent Extraction Agent (`src/agents/intent_agent.py`)
  - [x] Implement Gemini structured output for Matching & Ranking Agent (`src/agents/ranking_agent.py`)
  - [x] Replace static rejection check in Booking Agent (`src/agents/booking_agent.py`) with Gemini structured output check
  - [x] Verify the merged endpoint, structured outputs, and LLM-based rejection handling

