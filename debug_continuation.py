import os
import asyncio
import uuid
import sys
import json
import aiosqlite
from dotenv import load_dotenv

# Ensure we can import src
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/../../../../Music/informalServicesMPAgent"))

load_dotenv("c:/Users/User-1/Music/informalServicesMPAgent/.env")

from src.main import app
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def main():
    # Persistent connection for LangGraph checkpoints
    _db_conn = await aiosqlite.connect("checkpoints.sqlite", check_same_thread=False)
    checkpointer = AsyncSqliteSaver(_db_conn)
    
    from src.workflow import create_workflow
    workflow = create_workflow()
    graph = workflow.compile(checkpointer=checkpointer, interrupt_before=["simulate_booking"])
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "user_id": "debug_user",
        "messages": [{"role": "user", "content": "I need AC repair service in G-13 tomorrow morning at 10 AM"}],
        "logs": [],
    }
    
    print("--- Running Initial Turn ---")
    result = await graph.ainvoke(initial_state, config)
    print("Initial turn complete!")
    print("Next interrupted node(s):", (await graph.aget_state(config)).next)
    
    # Continuation
    print("\n--- Running Continuation Turn ---")
    state_snap = await graph.aget_state(config)
    messages = state_snap.values.get("messages", []) + [{"role": "user", "content": "Yes, please confirm the booking"}]
    
    print("Invoking graph for continuation...")
    result_cont = await graph.ainvoke({"messages": messages}, config)
    print("Continuation turn complete!")
    print("Result logs:", result_cont.get("logs"))
    
    await _db_conn.close()

if __name__ == "__main__":
    asyncio.run(main())
