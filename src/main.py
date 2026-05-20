import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.mongodb import MongoDBSaver
from pydantic import BaseModel

from src.agent_utils import assistant_messages, message_content, message_role
from src.agents.intent_agent import load_valid_services
from src.auth import get_current_user, router as auth_router
from src.config import get_mongodb_checkpoint_db, get_mongodb_uri, get_mongodb_db
from src.db import (
    close_mongodb,
    init_mongodb,
    get_bookings,
    get_messages,
    get_thread_owner,
    get_threads,
    migrate_database_schema,
    save_thread,
    thread_exists,
    update_thread_title,
    validate_database,
)
from src.workflow import create_workflow

load_dotenv()

graph = None
checkpointer = None


async def create_thread(user_id: str, thread_id: str, first_message: str) -> None:
    await save_thread(thread_id, user_id, title="New Conversation")


async def set_thread_title_from_message(thread_id: str, first_message: str) -> None:
    from src.agents.title_agent import generate_title

    title = await generate_title(first_message)
    await update_thread_title(thread_id, title)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, checkpointer
    init_mongodb(get_mongodb_uri(), get_mongodb_db())
    await migrate_database_schema()
    warnings = await validate_database()
    app.state.startup_warnings = warnings
    await load_valid_services()
    with MongoDBSaver.from_conn_string(
        get_mongodb_uri(),
        db_name=get_mongodb_checkpoint_db(),
    ) as mongo_checkpointer:
        checkpointer = mongo_checkpointer
        workflow = create_workflow()
        graph = workflow.compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
        yield
    close_mongodb()


app = FastAPI(title="Agentic AI Service Request API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Authentication"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal agent error", "detail": str(exc)},
    )


class RequestBody(BaseModel):
    text: str
    user_id: str = "anonymous"
    thread_id: str | None = None


def _resolve_status(state_snap, result: dict) -> str:
    next_nodes = state_snap.next if state_snap else []
    if "simulate_booking" in next_nodes:
        return "awaiting_confirmation"
    if result.get("booking_status", "").startswith("Pending:"):
        return "awaiting_confirmation"
    if result.get("confirmation_status") == "unclear":
        return "awaiting_confirmation"

    parsed = result.get("parsed_intent") or {}
    if parsed.get("service_type") and parsed.get("location") and not result.get("discovered_providers"):
        return "completed"

    if not next_nodes and not result.get("followup_plan"):
        if not result.get("booking_status", "").startswith("Failed"):
            return "awaiting_clarification"
    return "completed"


def _last_assistant_message(result: dict) -> str:
    msgs = result.get("messages") or []
    for m in reversed(msgs):
        role = message_role(m)
        if role in ("assistant", "ai"):
            return message_content(m)
    return result.get("booking_status", "")


def _fresh_turn_state(current_state: dict, req: RequestBody, messages: list[dict], user_id: str) -> dict:
    return {
        "user_id": current_state.get("user_id", user_id),
        "messages": messages,
        "logs": [],
        "discovered_providers": [],
        "selected_provider": None,
        "booking_status": "",
        "confirmation_status": "",
        "shown_provider_ids": [],
        "provider_preference": "",
        "requested_provider_name": "",
        "confirmation_prompt_override": "",
        "booking_id": None,
        "followup_plan": "",
        "parsed_intent": None,
    }


@app.post("/request")
async def request_endpoint(req: RequestBody, current_user: dict = Depends(get_current_user)):
    """Accept a user message and stream workflow progress as Server-Sent Events."""
    user_id = current_user["email"]
    if req.thread_id:
        thread_id = req.thread_id
        config = {"configurable": {"thread_id": thread_id}}
        if not await thread_exists(thread_id):
            raise HTTPException(status_code=404, detail="Thread not found")

        # Verify thread ownership
        thread_owner = await get_thread_owner(thread_id)
        if thread_owner != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this thread")

        state_snap = await graph.aget_state(config)
        current_state = state_snap.values if state_snap else {}
        messages = [*assistant_messages(current_state.get("messages", [])), {"role": "user", "content": req.text}]

        await graph.aupdate_state(config, {"messages": messages})

        if state_snap and state_snap.next:
            input_state = None
        else:
            input_state = _fresh_turn_state(current_state, req, messages, user_id)
    else:
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        await create_thread(user_id, thread_id, req.text)
        asyncio.create_task(set_thread_title_from_message(thread_id, req.text))

        input_state = {
            "user_id": user_id,
            "messages": [{"role": "user", "content": req.text}],
            "logs": [],
            "confirmation_status": "",
            "shown_provider_ids": [],
            "provider_preference": "",
            "requested_provider_name": "",
            "confirmation_prompt_override": "",
            "booking_id": None,
        }

    async def event_generator():
        initial_snap = await graph.aget_state(config)
        if input_state is not None:
            yielded_logs = set()
        else:
            yielded_logs = set(initial_snap.values.get("logs", [])) if (initial_snap and initial_snap.values) else set()

        final_state = {}

        try:
            async for event in graph.astream(input_state, config, stream_mode="updates"):
                for node_name, updates in event.items():
                    if not isinstance(updates, dict):
                        continue
                    agent_name = "".join(part.capitalize() for part in node_name.split("_"))

                    yield f"data: {json.dumps({'type': 'agent_start', 'agent': agent_name, 'message': f'{agent_name} is running...'})}\n\n"

                    for log in updates.get("logs", []):
                        if log not in yielded_logs:
                            yielded_logs.add(log)
                            parts = log.split(": ", 1)
                            log_event = {"type": "log", "agent": parts[0], "message": parts[1]} if len(parts) == 2 else {"type": "log", "agent": agent_name, "message": log}
                            yield f"data: {json.dumps(log_event)}\n\n"

                    final_state.update(updates)
                    await asyncio.sleep(0.08)
        except Exception as e:
            error_msg = f"Agent workflow error: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
            return

        state_snap = await graph.aget_state(config)
        complete_values = state_snap.values if (state_snap and state_snap.values) else final_state
        status = _resolve_status(state_snap, complete_values)

        payload = {
            "type": "done",
            "task_id": thread_id,
            "status": status,
            "assistant_message": _last_assistant_message(complete_values),
            "full_state": complete_values,
        }
        yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/threads/{user_id}")
async def list_user_threads(user_id: str, current_user: dict = Depends(get_current_user)):
    if user_id != current_user["email"]:
        raise HTTPException(status_code=403, detail="Not authorized to access threads for this user")
    return await get_threads(user_id)


@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["email"]
    # Verify thread ownership
    thread_owner = await get_thread_owner(thread_id)
    if thread_owner is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread_owner != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this thread")

    messages = await get_messages(thread_id, graph)
    return messages


@app.get("/bookings/{user_id}")
async def list_user_bookings(user_id: str, current_user: dict = Depends(get_current_user)):
    if user_id != current_user["email"]:
        raise HTTPException(status_code=403, detail="Not authorized to access bookings for this user")
    return await get_bookings(user_id)
