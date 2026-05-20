# Codebase Analysis & Frontend Integration Guide

## Codebase Analysis

### Issues Found

| # | File | Issue | Severity | Action |
|---|------|--------|----------|--------|
| 1 | `booking_agent.py` | `user_id` is hardcoded as `"user_123"` — every booking is attributed to the same user. | 🔴 High | **Fix:** Pass `user_id` via `RequestBody` → `AgentState` → booking agent. |
| 2 | `booking_agent.py` | Rejection check (`"no" in ans`) is fragile — `"no"` appears in words like "noted" or "notification". | 🔴 High | **Fix:** Use exact-match or a Gemini-classified intent instead. |
| 3 | `main.py` | `@app.on_event("startup")` is deprecated in FastAPI ≥ 0.93. | 🟠 Medium | **Fix:** Use `@asynccontextmanager lifespan` pattern. |
| 4 | `discovery_agent.py` | Uses synchronous `sqlite3` inside an async FastAPI handler — blocks the event loop. | 🟠 Medium | **Fix:** Switch to `aiosqlite` for async DB reads. |
| 5 | `intent_agent.py` | Opens a synchronous SQLite connection on every request to fetch valid service types. | 🟠 Medium | **Fix:** Cache this list at startup. |
| 6 | `main.py` | No global error handler — any agent exception returns a raw 500 with a Python traceback. | 🟠 Medium | **Fix:** Add `@app.exception_handler`. |
| 7 | `main.py` | `/ws/{task_id}` sends raw strings; no structure for the mobile app to parse agent-by-agent trace. | 🟡 Low | **Fix:** Send JSON events `{"agent": "...", "message": "..."}`. |
| 8 | `main.py` | Duplicate status-detection logic in both `/request` and `/reply` endpoints. | 🟡 Low | **Fix:** Extract to a `_resolve_status()` helper function. |
| 9 | `state.py` | `user_id` is not part of `AgentState`, so it can't flow through the graph. | 🟡 Low | **Fix:** Add `user_id: str` field. |
| 10 | `src/main.py` | `allow_origins=["*"]` with `allow_credentials=True` is a CORS misconfiguration — browsers reject this. | 🔴 High | **Fix:** Set specific origins or remove `allow_credentials` when using wildcard. |
| 11 | `db_setup.py` | `bookings` table has no `created_at` timestamp — can't sort or filter by recency. | 🟡 Low | **Fix:** Add `created_at DATETIME DEFAULT CURRENT_TIMESTAMP`. |

---

## Improvements Applied

All high/medium severity issues are fixed in the code. See changes below.

---

## Frontend Integration Guide (React Native + Expo)

### Conversation Flow State Machine

Your mobile app must track which state the conversation is in and adapt its UI accordingly:

```
idle → processing → awaiting_clarification → processing → ...
                 ↘ awaiting_confirmation → processing → completed
```

### API Contract

All requests use `Content-Type: application/json`.

#### `POST /request`
Start a new conversation.
```json
// Request
{ "text": "Mujhe G-13 mein AC technician chahiye", "user_id": "firebase_uid_abc123" }

// Response
{
  "task_id": "uuid-string",
  "status": "awaiting_confirmation" | "awaiting_clarification" | "completed",
  "assistant_message": "I found Ali AC Services for 1500 PKR. Shall I book?",
  "full_state": { ... }
}
```

#### `POST /reply/{task_id}`
Send any follow-up message (clarification answer OR booking confirmation).
```json
// Request
{ "text": "Yes, book it", "user_id": "firebase_uid_abc123" }

// Response — same shape as /request
```

#### `WS /ws/{task_id}`
Connect after sending a request to stream trace events.
```json
// Each WebSocket message is a JSON event:
{ "agent": "IntentAgent", "message": "Parsing intent from history." }
```

---

### React Native Hook (`useServiceAgent.ts`)

```typescript
import { useState, useRef, useCallback } from 'react';

// Use your machine's LAN IP when testing on a physical device
const API_BASE = __DEV__ ? 'http://192.168.x.x:8000' : 'https://your-production-api.com';
const WS_BASE  = __DEV__ ? 'ws://192.168.x.x:8000'  : 'wss://your-production-api.com';

export type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string };
export type AgentStatus = 'idle' | 'processing' | 'awaiting_clarification' | 'awaiting_confirmation' | 'completed';
export type TraceEvent  = { agent: string; message: string };

export function useServiceAgent(userId: string) {
  const [messages,   setMessages]   = useState<ChatMessage[]>([]);
  const [status,     setStatus]     = useState<AgentStatus>('idle');
  const [taskId,     setTaskId]     = useState<string | null>(null);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const _connectWs = (id: string) => {
    wsRef.current?.close();
    const ws = new WebSocket(`${WS_BASE}/ws/${id}`);
    ws.onmessage = (e) => {
      try {
        const event: TraceEvent = JSON.parse(e.data);
        setTraceEvents(prev => [...prev, event]);
      } catch {
        setTraceEvents(prev => [...prev, { agent: 'System', message: e.data }]);
      }
    };
    wsRef.current = ws;
  };

  const sendMessage = useCallback(async (text: string) => {
    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setStatus('processing');
    setTraceEvents([]);

    try {
      const url  = taskId ? `${API_BASE}/reply/${taskId}` : `${API_BASE}/request`;
      const body = JSON.stringify({ text, user_id: userId });
      const res  = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (!taskId) setTaskId(data.task_id);
      _connectWs(data.task_id ?? taskId);
      setStatus(data.status);

      if (data.assistant_message) {
        setMessages(prev => [...prev, {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.assistant_message,
        }]);
      }
    } catch (err) {
      console.error('Agent error:', err);
      setStatus('idle');
    }
  }, [taskId, userId]);

  const resetConversation = useCallback(() => {
    wsRef.current?.close();
    setMessages([]);
    setStatus('idle');
    setTaskId(null);
    setTraceEvents([]);
  }, []);

  return { messages, sendMessage, status, taskId, traceEvents, resetConversation };
}
```

### Chat Screen (`ServiceChatScreen.tsx`)

```tsx
import React, { useState } from 'react';
import { View, Text, TextInput, Pressable, FlatList, StyleSheet, ActivityIndicator } from 'react-native';
import { useServiceAgent } from '../hooks/useServiceAgent';

const STATUS_LABELS: Record<string, string> = {
  awaiting_clarification: 'Please provide more details.',
  awaiting_confirmation:  'Confirm your booking above ↑ (reply Yes or No)',
  completed:              '✅ Done!',
  processing:             '🤖 Agent is working...',
};

export default function ServiceChatScreen({ userId }: { userId: string }) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, traceEvents, resetConversation } = useServiceAgent(userId);

  const onSend = () => {
    if (!input.trim() || status === 'processing') return;
    sendMessage(input.trim());
    setInput('');
  };

  return (
    <View style={s.container}>
      <FlatList
        data={messages}
        keyExtractor={m => m.id}
        contentContainerStyle={{ paddingBottom: 12 }}
        renderItem={({ item }) => (
          <View style={[s.bubble, item.role === 'user' ? s.userBubble : s.aiBubble]}>
            <Text style={item.role === 'user' ? s.userText : s.aiText}>{item.content}</Text>
          </View>
        )}
      />

      {/* Live agent trace */}
      {status === 'processing' && traceEvents.length > 0 && (
        <View style={s.trace}>
          {traceEvents.slice(-3).map((e, i) => (
            <Text key={i} style={s.traceText}>• [{e.agent}] {e.message}</Text>
          ))}
        </View>
      )}

      {/* Status pill */}
      {status !== 'idle' && (
        <Text style={s.statusPill}>{STATUS_LABELS[status] ?? status}</Text>
      )}

      <View style={s.inputRow}>
        <TextInput
          style={s.input}
          value={input}
          onChangeText={setInput}
          placeholder="Koi service chahiye?"
          editable={status !== 'processing'}
          onSubmitEditing={onSend}
          returnKeyType="send"
        />
        {status === 'processing'
          ? <ActivityIndicator style={{ marginLeft: 8 }} />
          : <Pressable style={s.sendBtn} onPress={onSend}><Text style={s.sendTxt}>Send</Text></Pressable>
        }
      </View>

      <Pressable onPress={resetConversation}><Text style={s.reset}>+ New Request</Text></Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  container:  { flex: 1, backgroundColor: '#F7F7F7', padding: 12 },
  bubble:     { marginVertical: 4, padding: 12, borderRadius: 12, maxWidth: '82%' },
  userBubble: { backgroundColor: '#007AFF', alignSelf: 'flex-end' },
  aiBubble:   { backgroundColor: '#E8E8E8', alignSelf: 'flex-start' },
  userText:   { color: '#FFF', fontSize: 15 },
  aiText:     { color: '#111', fontSize: 15 },
  trace:      { backgroundColor: '#1A1A2E', padding: 8, borderRadius: 8, marginVertical: 6 },
  traceText:  { color: '#4CAF50', fontSize: 11, fontFamily: 'monospace' },
  statusPill: { textAlign: 'center', color: '#666', fontSize: 12, marginBottom: 4 },
  inputRow:   { flexDirection: 'row', alignItems: 'center' },
  input:      { flex: 1, backgroundColor: '#FFF', borderRadius: 24, paddingHorizontal: 16, paddingVertical: 10, borderWidth: 1, borderColor: '#DDD', fontSize: 15 },
  sendBtn:    { marginLeft: 8, backgroundColor: '#007AFF', borderRadius: 20, paddingHorizontal: 16, paddingVertical: 10 },
  sendTxt:    { color: '#FFF', fontWeight: '600' },
  reset:      { textAlign: 'center', color: '#007AFF', marginTop: 8, fontSize: 13 },
});
```

### Expo Physical Device Setup

When testing on a real Android/iOS device via Expo Go:
1. Find your PC's local IP: run `ipconfig` → look for `IPv4 Address`.
2. Replace `192.168.x.x` in the hook with your actual IP.
3. Start uvicorn bound to all interfaces:
   ```powershell
   uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. Ensure your phone and PC are on the **same Wi-Fi network**.

> [!WARNING]
> Android blocks HTTP cleartext traffic in production builds. Use HTTPS with a reverse proxy (nginx/Caddy) before deploying. During development with Expo Go this is not an issue.
