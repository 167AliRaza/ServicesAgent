# Walkthrough: Agentic AI Service Request System

I have successfully implemented the MVP for the Agentic AI System that handles service requests end-to-end. 

## What was built

1. **Environment & Data Layer**
   - Initialized the Python project using `uv`.
   - Setup a SQLite database (`service_agent.db`) via `db_setup.py` and populated it with dummy providers (AC Technicians, Plumbers, Electricians in locations like G-13 and F-8).

2. **Core Agents (LangGraph Nodes)**
   - **Intent Extraction (`src/agents/intent_agent.py`)**: Uses `google-generativeai` (Gemini 1.5 Flash) to parse Urdu, Roman Urdu, and English user requests into structured intents (`service_type`, `location`, `time`).
   - **Provider Discovery (`src/agents/discovery_agent.py`)**: Queries the SQLite mock database using fuzzy matching for the extracted service and location.
   - **Matching & Ranking (`src/agents/ranking_agent.py`)**: Passes the discovered providers to Gemini to pick the best one based on rating/price and formulate a natural language reasoning for the choice.
   - **Action Simulator (`src/agents/booking_agent.py`)**: Writes a mock `CONFIRMED` booking into the `bookings` table in SQLite.
   - **Follow-Up (`src/agents/followup_agent.py`)**: Generates follow-up reminder plans based on the successful booking.

3. **Orchestration & Interface**
   - **Workflow (`src/workflow.py`)**: Assembled the state graph using LangGraph to connect the agents sequentially and pass the `AgentState` object through the pipeline.
   - **FastAPI (`src/main.py`)**: Exposed the LangGraph workflow via a simple POST endpoint.

## How to Test and Verify

> [!IMPORTANT]
> You need a Gemini API key for the agents to function.
> 1. Create a `.env` file in the `informalServicesMPAgent` directory:
>    ```
>    GEMINI_API_KEY=your_actual_api_key_here
>    ```

### 1. Start the Server
Open your terminal in `c:\Users\User-1\Music\informalServicesMPAgent` and run:
```powershell
uv run uvicorn src.main:app --reload
```

### 2. Send a Request
You can test the agentic pipeline using `curl` or by visiting the Swagger UI at `http://127.0.0.1:8000/docs`.

**Example Request:**
```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/request-service" -ContentType "application/json" -Body '{"text": "Mujhe kal subah G-13 mein AC technician chahiye"}'
```

**Expected Response Structure:**
```json
{
  "user_input": "Mujhe kal subah G-13 mein AC technician chahiye",
  "parsed_intent": {
    "service_type": "AC Technician",
    "location": "G-13",
    "time": "kal subah"
  },
  "selected_provider": {
    "id": 1,
    "name": "Ali AC Services",
    "service_type": "AC Technician",
    "location": "G-13",
    "rating": 4.8,
    "base_price": 1500.0
  },
  "reasoning": "Ali AC Services has the highest rating (4.8) among the options.",
  "booking_status": "Slot booked for kal subah with Ali AC Services. Confirmation sent.",
  "followup_plan": "Reminder scheduled 1 hour before appointment. Status update queued for after completion.",
  "logs": [
    "IntentAgent: Parsing intent from input: 'Mujhe kal subah G-13 mein AC technician chahiye'",
    "IntentAgent: Successfully parsed intent -> {'service_type': 'AC Technician', 'location': 'G-13', 'time': 'kal subah'}",
    "DiscoveryAgent: Searching for 'AC Technician' in 'G-13'",
    "DiscoveryAgent: Found 2 providers",
    "RankingAgent: Evaluating 2 providers to pick the best one.",
    "RankingAgent: Selected provider 'Ali AC Services'. Reasoning: Ali AC Services has the highest rating.",
    "BookingAgent: Simulating booking with Ali AC Services at kal subah",
    "BookingAgent: Booking confirmed.",
    "FollowupAgent: Scheduling follow-up reminders."
  ]
}
```

The system beautifully executes the complete pipeline and records the `logs` trace to demonstrate its reasoning, tool usage, and simulated actions step-by-step.
