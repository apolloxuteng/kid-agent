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
uvicorn server:app --reload --host 0.0.0.0
```

Or run uvicorn via the venv’s Python (no activate needed):

```bash
./venv/bin/uvicorn server:app --reload --host 0.0.0.0
```

The API will be available at **http://localhost:8000**.

### Viewing log messages

Log output is printed in the **same terminal** where you run `uvicorn`. You’ll see:

- **Request logs** — e.g. `INFO:     127.0.0.1:... "POST /chat HTTP/1.1" 200` (from Uvicorn).
- **Application logs** — e.g. when the joke API is used:
  - `Joke API success: setup='...'... punchline='...'...` — external joke API returned a joke.
  - `Joke requested and injected into prompt (profile_id=...)` — user asked for a joke and a joke was injected.
  - `Joke requested but API returned none; ...` — user asked for a joke but the API failed or returned invalid data.

Log level defaults to **INFO**. To change it, set `LOG_LEVEL` before starting the server (e.g. `LOG_LEVEL=DEBUG` for more detail, or `LOG_LEVEL=WARNING` to reduce noise).

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

## Per-profile data (SQLite + optional encryption)

- Each child is identified by **profile_id** (e.g. the app’s UUID for that profile). Data is stored in a single **SQLite database** at **`data/kid_agent.db`** (tables: profiles, summaries, history).
- **Encryption at rest:** Set the environment variable **`KID_AGENT_DB_KEY`** to a Fernet key to encrypt sensitive columns (name, interests, summary, message content). Generate a key with Python: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`. Losing this key means encrypted data cannot be recovered; keep backups of the key and DB file secure.
- If `KID_AGENT_DB_KEY` is not set, data is stored in plaintext (existing DB rows remain readable).
- **Memory is isolated per profile**: history and summary for one child never affect another. Resetting or clearing is per profile_id.
- **Migration from file-based storage:** If you had data in `data/profiles/` before switching to SQLite, run once: `python scripts/migrate_to_sqlite.py` from the backend directory (with the server stopped). This copies existing profile.json, summary.txt, and history.json into the database.

## Conversation memory

- For each profile, the server **loads** that profile’s history and summary from the database, builds the prompt (system + profile + summary + last 10 messages), calls the LLM, then **saves** updated history and summary back to the database.
- History is **capped at 100 messages** per profile; a short summary is updated every 10 messages so context stays bounded without sending the full history every time.
- **POST /reset?profile_id=...** clears history and summary for that profile only.

## Child profile (per profile_id)

- Each profile has its own **profile.json** (name and interests) so the assistant can personalize replies (e.g. use the child’s name, mention their interests).
- **How it’s updated:** Simple pattern matching on the user’s message (no extra LLM call). For example: “my name is Emma” → name is set; “I like dinosaurs” → “dinosaurs” is added to interests. Interests are capped at 10.
- **POST /profile/reset?profile_id=...** clears name and interests for that profile only.

## Configuration

- **Environment:** `KID_AGENT_DB_KEY` — optional Fernet key for encrypting stored data (see Per-profile data above). You can put it in a **`backend/.env`** file (loaded automatically; do not commit `.env`). See [Moving the server to another machine](#moving-the-server-to-another-machine-eg-via-github) if you deploy or clone the repo elsewhere.
- In `server.py` you can change:
  - `OLLAMA_URL` — default `http://localhost:11434/api/generate`
  - `MODEL_NAME` — default `llama3`

Make sure Ollama is running and the model is pulled before calling `/chat`.

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

**"Ollama request failed: 404 Client Error: Not Found for url: .../api/generate"**

Ollama returns 404 when the **model** is missing or the name is wrong. Fix it:

1. List installed models: `ollama list`
2. Pull the default model: `ollama pull llama3`  
   Or use a model you already have (e.g. `qwen2.5`, `llama3.2:latest`) and set that name in `server.py` as `MODEL_NAME`.
3. Restart the kid-agent server and try again.
