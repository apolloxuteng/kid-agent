# Kid Agent Backend

A minimal FastAPI backend that sends messages to a **local LLM** with a kid-friendly personality and **conversation memory**. It supports **Ollama** by default and **LM Studio** via its OpenAI-compatible API. Designed for a child and meant to run on a Mac home server.

## Prerequisites

- **Python 3.11+**
- One local LLM server:
  - **Ollama** installed and running locally (e.g. `ollama serve` and `ollama pull qwen2.5`), or
  - **LM Studio** running its local server with a tool-capable model loaded.

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
uvicorn server:app --reload --host 0.0.0.0
```

Or run uvicorn via the venv’s Python (no activate needed):

```bash
./venv/bin/uvicorn server:app --reload --host 0.0.0.0
```

The API will be available at **http://localhost:8000**.

### Using LM Studio instead of Ollama

Start LM Studio's local server on the Mac that runs this backend, load your model, then run:

```bash
LLM_PROVIDER=lmstudio \
MODEL_NAME=google/gemma-4-26b-a4b \
LMSTUDIO_BASE_URL=http://localhost:1234/v1 \
uvicorn server:app --reload --host 0.0.0.0
```

You can also put those values in `backend/.env`:

```bash
LLM_PROVIDER=lmstudio
MODEL_NAME=google/gemma-4-26b-a4b
LMSTUDIO_BASE_URL=http://localhost:1234/v1
```

### Viewing log messages

Log output is printed in the **same terminal** where you run `uvicorn`. You’ll see:

- **Request logs** — e.g. `INFO:     127.0.0.1:... "POST /chat HTTP/1.1" 200` (from Uvicorn).
- **Application logs** — e.g. timing and direct tool use:
  - `chat_stream first token ... elapsed=...` — time until the first streamed token.
  - `chat_stream completed ... total=... save=...` — total request and save timing.
  - `Direct tool fast path: get_joke` — request was handled without an LLM round trip.
  - `Joke API success: setup='...'... punchline='...'...` — external joke API returned a joke.

Log level defaults to **INFO**. To change it, set `LOG_LEVEL` before starting the server (e.g. `LOG_LEVEL=DEBUG` for more detail, or `LOG_LEVEL=WARNING` to reduce noise).

## Testing

- **Interactive docs:** Open **http://localhost:8000/docs** in your browser. Use the **POST /chat** endpoint to send a message and see the JSON reply.
- **Health check:** **GET http://localhost:8000/health** should return `{"status":"ok"}`.

## API Summary

| Method | Path    | Description |
|--------|---------|-------------|
| GET    | /health | Health check; returns `{"status":"ok"}` |
| GET    | /profile | Returns the stored child profile for `profile_id` (query: `?profile_id=...`). |
| GET    | /words | Returns recently taught vocabulary words for `profile_id` (query: `?profile_id=...&limit=100`). |
| DELETE | /words/{word_id} | Deletes one learned word for `profile_id` (query: `?profile_id=...`). |
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

## Per-profile data (SQLite + optional encryption)

- Each child is identified by **profile_id** (e.g. the app’s UUID for that profile). Data is stored in a single **SQLite database** at **`data/kid_agent.db`** (tables: profiles, summaries, history, learned_words).
- **Encryption at rest:** Set the environment variable **`KID_AGENT_DB_KEY`** to a Fernet key to encrypt sensitive columns (name, interests, summary, message content). Generate a key with Python: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`. Losing this key means encrypted data cannot be recovered; keep backups of the key and DB file secure.
- If `KID_AGENT_DB_KEY` is not set, data is stored in plaintext (existing DB rows remain readable).
- **Memory is isolated per profile**: history and summary for one child never affect another. Resetting or clearing is per profile_id.
- **Migration from file-based storage:** If you had data in `data/profiles/` before switching to SQLite, run once: `python scripts/migrate_to_sqlite.py` from the backend directory (with the server stopped). This copies existing profile.json, summary.txt, and history.json into the database.

## Conversation memory

- For each profile, the server **loads** that profile’s history and summary from the database, builds the prompt (system + profile + summary + recent messages), calls the LLM, then **saves** updated history and summary back to the database.
- History is **capped at 300 messages** per profile by default, and the prompt includes the most recent **40 messages** by default. A short summary is updated every **50 stored messages** by default so context stays useful without frequent background LLM calls. These defaults can be overridden with environment variables.
- **POST /reset?profile_id=...** clears history and summary for that profile only.

## Child profile (per profile_id)

- Each profile has its own **profile.json** (name and interests) so the assistant can personalize replies (e.g. use the child’s name, mention their interests).
- **How it’s updated:** Simple pattern matching on the user’s message (no extra LLM call). For example: “my name is Emma” → name is set; “I like dinosaurs” → “dinosaurs” is added to interests. Interests are capped at 10.
- **POST /profile/reset?profile_id=...** clears name and interests for that profile only.

## Tool calling and direct routing

The backend uses direct local routing for clear requests (joke, word of the day, word definition, learned-word review, calculation) and falls back to the configured model's **tool-calling API** for ambiguous tool requests. The LLM sees a small tool set and returns `tool_calls`; the server runs those tools, then sends results back for a final reply.

- **Model:** Use a model/server combination that supports tool calling. For Ollama, examples include **qwen2.5** and **llama3.1**. For LM Studio, enable the local server and use its model id in `MODEL_NAME` (for example `google/gemma-4-26b-a4b`). If the model/server does not support tools, you may get 404, rejected requests, or empty `tool_calls`.
- **Active in-process tools:** `get_joke`, `get_word_of_day`, `define_word`, `review_learned_words`, and `calculate`.

### Adding a local tool

1. In **`routing/local_tools.py`**, implement a tool that satisfies the **in-process tool** protocol: `name`, `description`, `parameters_schema`, and `async def run(ctx, arguments) -> ToolResult`. Use `RoutingContext` (user_message, last_assistant_message, profile_id, conversation_history) and return a `ToolResult(text=...)`.
2. Add the tool instance to **`ALL_IN_PROCESS_TOOLS`** in the same file. It will be registered at import time and appear in the list of tools sent to Ollama.
3. No changes are needed in `server.py` or the if/elif routing — the model will see the new tool and can call it by name.

## Configuration

- **Environment:** You can put these in a **`backend/.env`** file (loaded automatically; do not commit `.env`). See [Moving the server to another machine](#moving-the-server-to-another-machine-eg-via-github) if you deploy or clone the repo elsewhere.
  - **`KID_AGENT_DB_KEY`** — optional Fernet key for encrypting stored data (see Per-profile data above).
- In **`llm.py`** you can change:
  - **`OLLAMA_URL`** — default `http://localhost:11434/api/generate` (chat uses `/api/chat` automatically).
  - **`LLM_PROVIDER`** — `ollama` by default; set to `lmstudio` to use LM Studio.
  - **`MODEL_NAME`** — default `qwen2.5` for Ollama, or `google/gemma-4-26b-a4b` when `LLM_PROVIDER=lmstudio`; must be a model that supports **tool calling**. Set this in `.env` on the server so model changes do not require code edits.
  - **`LMSTUDIO_BASE_URL`** — default `http://localhost:1234/v1`; used only when `LLM_PROVIDER=lmstudio`.
  - **`RECENT_MESSAGES_COUNT`** — default `40`; number of recent messages sent to the LLM.
  - **`MAX_HISTORY_MESSAGES`** — default `300`; maximum stored history messages per profile.
  - **`SUMMARY_EVERY_MESSAGES`** — default `50`; how often to refresh the profile summary.
  - **`ENABLE_SUMMARY`** — default `true`; set to `false` to disable background summary calls.

Make sure the selected LLM server is running and the model is loaded before calling `/chat`.

## Moving the server to another machine (e.g. via GitHub)

When you clone or copy this repo to a **new server**, the following are **not** in the repo (they are in `.gitignore`):

- **`.env`** — contains `KID_AGENT_DB_KEY`; never commit this file.
- **`data/`** — the SQLite database and any legacy `data/profiles/` folders.

**To run successfully on the new server:**

1. **Clone/copy the repo** (e.g. from GitHub) and install dependencies:
   ```bash
   cd kid-agent/backend
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Encryption key (only if you need it):**
   - **If you are copying the existing database** (`data/kid_agent.db`) to the new server and want to read that data: create a **`.env`** file in the `backend` folder and set the **same** key you used on the old server:
     ```bash
     # In backend/.env (create this file on the new server)
     KID_AGENT_DB_KEY=<paste your Fernet key here>
     ```
     Transfer the key securely (e.g. password manager, secure channel). Do **not** put it in GitHub.
   - **If you are starting fresh** (no copied database): the server runs without a key (data stored in plaintext). You can optionally generate a new key and add it to `.env` if you want encryption on the new server.

3. **Database on the new server:**  
   If you did not copy `data/kid_agent.db`, the server will create a new empty database on first run. If you did copy the DB, ensure the same `KID_AGENT_DB_KEY` is in `.env` so encrypted data can be decrypted.

4. **Run the server** as usual (`uvicorn server:app --reload --host 0.0.0.0`). The server loads `backend/.env` automatically if present.

## Troubleshooting

**"ModuleNotFoundError: No module named 'httpx'"**


The server needs `httpx` (and other deps) from the project venv. Use the venv when running:

1. `cd kid-agent/backend && source venv/bin/activate`
2. `pip install -r requirements.txt`  (if you just created the venv or added deps)
3. `uvicorn server:app --reload --host 0.0.0.0`

If you use `--reload`, start uvicorn with the venv’s interpreter (e.g. `./venv/bin/uvicorn server:app --reload --host 0.0.0.0` or run `uvicorn` after `source venv/bin/activate`) so the reload subprocess sees the same packages.

**"Ollama request failed: 404 Client Error: Not Found for url: .../api/chat"** (or `/api/generate`)

Ollama returns 404 when the **model** is missing, the name is wrong, or the model does not support tool calling. Fix it:

1. List installed models: `ollama list`
2. Use a **tool-capable** model (e.g. `qwen2.5`, `llama3.1`): `ollama pull qwen2.5`
3. Set `MODEL_NAME` in `.env` or in `llm.py` to that model (default is `qwen2.5`).
4. Restart the kid-agent server and try again.
