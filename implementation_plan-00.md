# Agentic AI Service Request System: MVP Implementation Plan

This document outlines the architecture, tech stack, and step-by-step plan to build an MVP of the Agentic AI System that automates the lifecycle of service requests.

## Goal Description
Build an end-to-end Agentic AI workflow that understands natural language service requests (in Urdu, Roman Urdu, and English), discovers and ranks relevant providers, simulates the booking process, and schedules follow-up actions. The system will clearly expose its reasoning and execution trace at each step.

> [!NOTE]
> We will use an agentic state-machine approach. This ensures that the reasoning pipeline (planning → decision → action → follow-up) is strictly followed, and all tool usage and decisions are easily traceable and loggable.

## Proposed Architecture & Tech Stack

- **Language:** Python
- **Agent Framework:** **LangGraph** (Ideal for building structured, stateful, multi-agent workflows with clear observability and branching logic).
- **LLM:** **Gemini 1.5 Pro / Flash** (Excellent multilingual capabilities, specifically for nuanced languages like Urdu and Roman Urdu, and strong function calling support).
- **Data Layer:** SQLite or static JSON files (for simulating the provider database and booking registry).

### Workflow Pipeline (LangGraph Nodes)
The system will maintain a shared "State" (e.g., `user_input`, `parsed_intent`, `discovered_providers`, `selected_provider`, `booking_details`, `followup_plan`).

1. **Intent Extraction Agent:** 
   - Takes raw user text.
   - Uses Structured Outputs to extract `service_type` (e.g., "AC Technician"), `location` (e.g., "G-13"), and `time` (e.g., "Tomorrow morning").
2. **Provider Discovery Agent:**
   - Queries a mock database to find providers matching the `service_type` and `location`.
3. **Matching & Ranking Agent:**
   - Evaluates providers based on simulated distance, rating, and availability.
   - Selects the best match and generates a natural language explanation (reasoning) for the choice.
4. **Action Simulator Agent:**
   - Creates a booking record in the mock database.
   - Generates a simulated confirmation receipt/message.
5. **Follow-Up Agent:**
   - Drafts reminder messages and schedules them (e.g., "Reminder scheduled 1 hour before").

## Proposed Changes

### Phase 1: Environment & Mock Data
- Initialize a new Python project with Poetry or pip.
- Set up dependencies: `langgraph`, `langchain-google-genai`, `pydantic`.
- Create `data/providers.json` with mock data (e.g., AC Technicians, Plumbers in G-13, F-8 with dummy ratings and coordinates).

### Phase 2: Core Agents Implementation
- **`agents/intent_agent.py`**: Prompt engineering to parse English, Urdu, and Roman Urdu into Pydantic models.
- **`agents/discovery_agent.py`**: Python logic to filter `providers.json`.
- **`agents/ranking_agent.py`**: LLM + Python logic to rank and generate reasoning.
- **`agents/booking_agent.py`**: Simulates database writes and generates confirmation strings.
- **`agents/followup_agent.py`**: Generates post-booking scheduling logic.

### Phase 3: Workflow Orchestration & Interface
- **`workflow.py`**: Assemble the LangGraph pipeline, connecting nodes and defining state transitions.
- **`main.py`**: A CLI application that takes user input, runs the graph, and beautifully prints the execution logs (decisions, tool usage, action execution) step-by-step.

## User Review Required

> [!IMPORTANT]
> Please review the following design questions before we begin execution:

1. **Framework Choice:** I proposed **LangGraph** in Python because it is the industry standard for stateful, traceable workflows. Are you comfortable with this, or would you prefer another framework like CrewAI, or just a pure custom Python script?
2. **Interface:** For the MVP, I plan to build a **CLI (Command Line Interface)** that cleanly prints out the reasoning steps and final output. Would you prefer this, or a simple Web UI (like Streamlit)?
3. **Mock Data:** I will start with a mock dataset (JSON) for providers to ensure the MVP works instantly without API keys for Google Maps. Is this acceptable for the first version?

## Verification Plan

### Automated/Manual Testing
- Run the CLI with the example prompt: `"Mujhe kal subah G-13 mein AC technician chahiye"`
- Verify that the system outputs the extracted intent, the discovered providers, the reasoning for the top pick, the simulated booking, and the follow-up plan.
- Test edge cases (e.g., missing time, unsupported locations, pure English input, pure Urdu script input).
