"""
Stub for the freellmapi service.

This stub provides an OpenAI-compatible API surface on port 11434 for the
walking skeleton. Replace with ghcr.io/codefuse-ai/freellmapi:latest (or the
canonical freellmapi image) once registry access is configured.

freellmapi routes requests to free LLM providers (e.g., deepseek, codellama).
The real integration ships in a later plan; this stub lets the network topology
be verified end-to-end without requiring an LLM backend.
"""
from fastapi import FastAPI

app = FastAPI(title="freellmapi-stub")


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "service": "freellmapi-stub"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/generate")
async def generate(body: dict = None) -> dict:  # type: ignore[assignment]
    return {
        "model": (body or {}).get("model", "stub"),
        "response": "[freellmapi stub — configure real image for LLM responses]",
        "done": True,
    }


@app.post("/v1/chat/completions")
async def chat_completions(body: dict = None) -> dict:  # type: ignore[assignment]
    return {
        "id": "stub-0",
        "object": "chat.completion",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "[freellmapi stub — configure real image for LLM responses]",
                },
                "finish_reason": "stop",
                "index": 0,
            }
        ],
    }
