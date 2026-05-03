"""openai-api — sibling of claude-cli-api.

Same POST /chat contract so the pipeline's provider abstraction can swap
backends without touching agents. Two extras over the Claude wrapper:

  - REAL token usage in the response body (no estimation).
  - Optional `json_schema` parameter that uses OpenAI Structured Outputs to
    GUARANTEE the reply matches a schema (eliminates the parse-and-retry
    loop on the agent side).

Endpoints:
  POST /chat   → call OpenAI, return reply_text + usage
  GET  /health → liveness + key/mock status
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import openai_client

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="OpenAI CICD Backend", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message:       str
    context:       list[str] = []
    system_prompt: Optional[str] = None
    json_schema:   Optional[dict] = None
    model:         Optional[str] = None


class Usage(BaseModel):
    tokens_in:    int
    tokens_out:   int
    cached_tokens: int = 0
    duration_s:   float
    model:        str
    mocked:       bool = False


class ChatResponse(BaseModel):
    reply_text: str
    usage:      Usage


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "openai_available": openai_client.is_available(),
        "mock_mode":        openai_client.MOCK_ENABLED,
        "default_model":    openai_client.DEFAULT_MODEL,
        "has_api_key":      bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip() and not req.json_schema:
        raise HTTPException(status_code=400, detail="message must not be empty")
    try:
        result = await openai_client.call_openai(
            user_prompt=req.message,
            system_prompt=req.system_prompt,
            context_lines=req.context or None,
            json_schema=req.json_schema,
            model=req.model,
        )
    except openai_client.OpenAIClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return ChatResponse(
        reply_text=result.text,
        usage=Usage(
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cached_tokens=result.cached_tokens,
            duration_s=round(result.duration_s, 3),
            model=result.model,
            mocked=result.mocked,
        ),
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0",
                port=int(os.getenv("PORT", "8300")), reload=True)
