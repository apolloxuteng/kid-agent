# Kid Agent Backend

A minimal FastAPI backend that sends messages to a **local LLM (Ollama)** with a kid-friendly personality and **conversation memory**. Designed for a 5-year-old child and meant to run on a Mac Mini home server.

## Prerequisites

- **Python 3.11+**
- **Ollama** installed and running locally (e.g. `ollama serve` and `ollama pull llama3`)

## Setup

### 1. Create a virtual environment

```bash
cd kid-agent/backend
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the server

**Use the venv** so all dependencies (including `httpx`) are found:

```bash
source venv/bin/activate
uvicorn server:app --reload
```

Or run uvicorn via the venv’s Python (no activate needed):

```bash
./venv/bin/uvicorn server:app --reload
```

The API will be available at **http://localhost:8000**.

## Testing

- **Interactive docs:** Open **http://localhost:8000/docs** in your browser. Use the **POST /chat** endpoint to send a message and see the JSON reply.
- **Health check:** **GET http://localhost:8000/health** should return `{"status":"ok"}`.

## API Summary

| Method | Path    | Description |
|--------|---------|-------------|
| GET    | /health | Health check; returns `{"status":"ok"}` |
| GET    | /profile | Returns the stored child profile for `profile_id` (query: `?profile_id=...`). |
| POST   | /chat   | Send a message; body: `{"message": "your text", "profile_id": "uuid-or-id"}`; returns `{"reply": "..."}`. All memory and profile updates apply only to that profile. |
| POST   | /chat/stream | Same as /chat but streams the reply as Server-Sent Events (SSE). See [Streaming](#streaming-post-chatstream) below. |
| POST   | /reset  | Clear conversation memory for one profile; query: `?profile_id=...`. |
| POST   | /profile/reset | Clear the child profile (name and interests) for one profile; query: `?profile_id=...`. |

## Streaming (POST /chat/stream)

**POST /chat/stream** uses the same request body as **POST /chat** but returns a **Server-Sent Events (SSE)** stream so the client can show tokens as they arrive.

- **Event format:** Each SSE event is a single line: `data: <JSON>`. The JSON object can be:
  - `{"token": "..."}` — one piece of the reply; the client should append this to the displayed message.
  - `{"done": true, "reply": "..."}` — stream finished; `reply` is the full assistant message (use this for history/TTS if you prefer).
  - `{"error": "..."}` — something went wrong (e.g. Ollama down); no reply is stored.
- **Backward compatibility:** The non-streaming **POST /chat** is unchanged; existing clients keep working.

### iOS app changes to use streaming

To use **POST /chat/stream** from the iOS app for lower perceived latency:

1. **Request:** Use `URLSession` or `URLSessionConfiguration` with a POST to `.../chat/stream` and the same JSON body (`message`, `profile_id`). Do not expect a single JSON response; the response body is an SSE stream.
2. **Consume the stream:** Read the response body as a stream (e.g. `URLSessionDelegate` with `urlSession(_:dataTask:didReceive data:)` or `AsyncThrowingStream` over the bytes). Parse line by line; when a line starts with `data: `, parse the rest as JSON.
3. **Update UI:** For each `{"token": "..."}` event, append the value to the current message and refresh the bubble. When you receive `{"done": true, "reply": "..."}`, treat the message as complete (e.g. trigger TTS on `reply`).
4. **Errors:** On `{"error": "..."}` or a broken stream, show an error and do not add a reply to the conversation.

No backend changes are required beyond calling `/chat/stream` instead of `/chat`; history and profile updates behave the same.

## Per-profile data (no database)

- Each child is identified by **profile_id** (e.g. the app’s UUID for that profile). Data is stored under **`data/profiles/{profile_id}/`**:
  - **profile.json** — name and interests (updated from messages)
  - **summary.txt** — short conversation summary (updated every 6 messages)
  - **history.json** — recent messages for context
- The folder is **created automatically** when a profile is first used (e.g. first chat with that profile_id). No setup required.
- **Memory is isolated per profile**: history and summary for one child never affect another. Resetting or clearing is per profile_id.

## Conversation memory

- For each profile, the server **loads** that profile’s history and summary from disk, builds the prompt (system + profile + summary + last 6 messages), calls the LLM, then **saves** updated history and summary back to that profile’s folder.
- History is **capped at 50 messages** per profile; a short summary is updated every 6 messages so context stays bounded without sending the full history every time.
- **POST /reset?profile_id=...** clears history and summary for that profile only.

## Child profile (per profile_id)

- Each profile has its own **profile.json** (name and interests) so the assistant can personalize replies (e.g. use the child’s name, mention their interests).
- **How it’s updated:** Simple pattern matching on the user’s message (no extra LLM call). For example: “my name is Emma” → name is set; “I like dinosaurs” → “dinosaurs” is added to interests. Interests are capped at 10.
- **POST /profile/reset?profile_id=...** clears name and interests for that profile only.

## Configuration

In `server.py` you can change:

- `OLLAMA_URL` — default `http://localhost:11434/api/generate`
- `MODEL_NAME` — default `llama3`

Make sure Ollama is running and the model is pulled before calling `/chat`.

## Troubleshooting

**"ModuleNotFoundError: No module named 'httpx'"**

The server needs `httpx` (and other deps) from the project venv. Use the venv when running:

1. `cd kid-agent/backend && source venv/bin/activate`
2. `pip install -r requirements.txt`  (if you just created the venv or added deps)
3. `uvicorn server:app --reload`

If you use `--reload`, start uvicorn with the venv’s interpreter (e.g. `./venv/bin/uvicorn` or run `uvicorn` after `source venv/bin/activate`) so the reload subprocess sees the same packages.

**"Ollama request failed: 404 Client Error: Not Found for url: .../api/generate"**

Ollama returns 404 when the **model** is missing or the name is wrong. Fix it:

1. List installed models: `ollama list`
2. Pull the default model: `ollama pull llama3`  
   Or use a model you already have (e.g. `qwen2.5`, `llama3.2:latest`) and set that name in `server.py` as `MODEL_NAME`.
3. Restart the kid-agent server and try again.
