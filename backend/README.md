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

```bash
uvicorn server:app --reload
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
| POST   | /reset  | Clear conversation memory for one profile; query: `?profile_id=...`. |
| POST   | /profile/reset | Clear the child profile (name and interests) for one profile; query: `?profile_id=...`. |

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

**"Ollama request failed: 404 Client Error: Not Found for url: .../api/generate"**

Ollama returns 404 when the **model** is missing or the name is wrong. Fix it:

1. List installed models: `ollama list`
2. Pull the default model: `ollama pull llama3`  
   Or use a model you already have (e.g. `qwen2.5`, `llama3.2:latest`) and set that name in `server.py` as `MODEL_NAME`.
3. Restart the kid-agent server and try again.
