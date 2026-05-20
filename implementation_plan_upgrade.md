# Agentic AI Service Request System: Upgrade & HITL Implementation Plan

This plan addresses upgrading the SDK, updating the model to `gemini-2.5-flash-lite`, and adding multi-turn interactive capabilities (Clarifications & Human-in-the-loop Booking Confirmation).

## Goal Description
1. **SDK Upgrade:** Migrate from the older `google-generativeai` SDK to the new `google-genai` SDK and switch to the `gemini-2.5-flash-lite` model for faster, lightweight inference.
2. **Conditional Routing (Clarification):** If the `IntentExtractionAgent` fails to extract a `location` or `service_type`, the workflow should dynamically route to a `ClarificationAgent` to ask the user a follow-up question.
3. **Human-in-the-Loop (HITL) Booking:** Before simulating the actual booking, the workflow must pause and ask the user for confirmation. Once the user confirms, the workflow resumes and simulates the booking.

> [!NOTE]
> To support multi-turn conversations and pausing (HITL), we will introduce a **Persistent Checkpointer** (`MemorySaver`) into the LangGraph workflow. This requires tracking conversations via a `thread_id` in the API.

## Proposed Architecture Updates

### 1. State & Checkpointing
- **State (`src/state.py`):** We will update the state to handle multi-turn interactions and flags.
  - Add `thread_id` conceptually at the API level.
  - Keep track of `messages` (chat history) rather than just a single `user_input`, allowing the intent parser to read previous turns when parsing clarification answers.
  - Add `awaiting_confirmation: bool` or use LangGraph's native `interrupt` functionality.

### 2. Upgrading `google.genai`
- Replace `import google.generativeai` with `from google import genai`.
- Refactor generation calls to use `client.models.generate_content(model="gemini-2.5-flash-lite", ...)`.

### 3. New Nodes & Conditional Edges
- **Clarification Node (`src/agents/clarification_agent.py`):** Generates a polite question asking for missing parameters.
- **Conditional Edge (`check_intent`):** 
  - After `parse_intent`, check if `service_type` and `location` are present.
  - If missing -> route to `ask_clarification`.
  - If complete -> route to `discover_providers`.
- **HITL Edge (`check_confirmation`):**
  - We will use LangGraph's idiomatic `interrupt_before=["simulate_booking"]` or create an `ask_confirmation` node that pauses the state. 
  - When the user replies "yes", we resume the graph to hit `simulate_booking`.

## Proposed Changes

### [MODIFY] `src/state.py`
- Update `AgentState` to include `messages: list[dict]`, `missing_fields: list[str]`, and `requires_confirmation: bool`.

### [MODIFY] `src/agents/intent_agent.py` & `src/agents/ranking_agent.py`
- Refactor to use `google.genai` and `gemini-2.5-flash-lite`.
- Update prompt in `intent_agent` to read from the entire `messages` history to understand follow-up clarifications.

### [NEW] `src/agents/clarification_agent.py`
- Logic to generate: *"I need to know the service type and your location. What do you need?"*

### [NEW] `src/agents/confirmation_agent.py`
- Logic to generate: *"I found Ali AC Services for 1500 PKR. Do you want me to book this? (Yes/No)"*

### [MODIFY] `src/workflow.py`
- Import `MemorySaver` from `langgraph.checkpoint.memory`.
- Add conditional edges `check_intent_complete` and `check_user_confirmation`.
- Compile with `checkpointer=MemorySaver()` and `interrupt_before=["simulate_booking"]`.

### [MODIFY] `src/main.py`
- Update FastAPI endpoints to accept a `thread_id`.
- Handle cases where the graph is suspended (waiting for clarification or confirmation) and needs to be resumed with the user's next message.

## User Review Required

> [!IMPORTANT]
> 1. **Thread IDs in API:** To pause and resume a workflow (HITL), the API needs to know which user/session is talking. I will update the `POST /api/v1/request-service` endpoint to accept a `thread_id` (string). Is this acceptable?
> 2. **API Response Structure:** When the graph pauses for clarification or confirmation, the API will return early with a "status" like `awaiting_clarification` or `awaiting_confirmation` along with the bot's message. Does this fit your expectations for the MVP?

## Verification Plan
1. Send an incomplete request: `"Mujhe AC technician chahiye"`. Verify the API asks for location.
2. Reply with `"G-13"`. Verify it discovers providers, ranks them, and pauses to ask for confirmation.
3. Reply with `"Yes"`. Verify it simulates the booking and schedules follow-ups.
4. Verify all LLM calls use `google.genai` and `gemini-2.5-flash-lite`.
