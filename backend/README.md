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
| GET    | /profile | Returns the stored child profile: `{"name": "...", "interests": [...]}`. |
| POST   | /chat   | Send a message; body: `{"message": "your text"}`; returns `{"reply": "..."}`. Uses in-memory conversation history and updates the child profile from simple phrases (e.g. "my name is X", "I like X"). |
| POST   | /reset  | Clear conversation memory; returns `{"status": "memory cleared"}`. Use when starting a new topic or session. |
| POST   | /profile/reset | Clear the child profile (name and interests) and save to file. |

## Conversation memory

- The server keeps a **conversation history** in RAM (a list of user and assistant messages). When you send a new message, the prompt sent to the LLM includes the last 10 exchanges so the assistant can answer in context (e.g. "What color was it?" after you talked about a car).
- Memory is **in-memory only**: no database or files. It persists only while the server is running. When you stop the server, history is lost. This keeps the project simple and avoids storing data on disk.
- History is **capped at 20 messages** so the list does not grow forever and the prompt stays a reasonable size for the model.
- **POST /reset** clears the history. Call it when the child starts a new topic or you want a fresh conversation.

## Child profile memory

- The server keeps a **child profile** (name and interests) so the assistant can personalize replies (e.g. use the child’s name, mention their interests). This is **separate** from conversation history: the profile is **persistent** and stored in a file.
- **Where it’s stored:** In the backend folder, in a file named **`child_profile.json`**. The server loads it at startup and saves it whenever the profile is updated from a message.
- **How it’s updated:** Simple pattern matching on the user’s message (no extra LLM call). For example: “my name is Emma” → name is set; “I like dinosaurs” → “dinosaurs” is added to interests. Interests are capped at 10; very long or empty values are ignored.
- **How to reset the profile:** Call **POST /profile/reset** to clear name and interests and overwrite the file. Or delete `child_profile.json` manually and restart the server.

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
