"""Claude CLI API — standalone FastAPI server.

Endpoints:
  POST /chat          → call Claude CLI, return reply + optional plan
  GET  /health        → liveness check + CLI availability
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import claude_cli
import gemini_cli
import planner
from config import HTTP_PORT

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Claude CLI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    context: List[str] = []
    system_prompt: Optional[str] = None
    attachments: Optional[List[str]] = None
    # v3 production additions:
    backend: Optional[str] = None       # "claude" | "gemini" — overrides PLANNER_BACKEND for this call
    json_schema: Optional[Dict] = None  # advisory: not enforced by either CLI; kept for parity


class Usage(BaseModel):
    backend:    str
    duration_s: float


class ChatResponse(BaseModel):
    reply_text: str
    plan: Optional[Dict] = None
    usage: Optional[Usage] = None


@app.get("/health")
async def health():
    claude_available = await claude_cli.is_available()
    gemini_available = await gemini_cli.is_available()
    return {
        "status": "ok",
        "claude_cli_available": claude_available,
        "gemini_cli_available": gemini_available
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip() and not req.attachments:
        raise HTTPException(status_code=400, detail="message or attachments must not be empty")

    import time as _t
    t0 = _t.time()
    result = await planner.generate_reply(
        user_text=req.message,
        context_lines=req.context or None,
        system_prompt=req.system_prompt,
        attachments=req.attachments,
        backend_override=req.backend,
    )
    dur = _t.time() - t0
    backend_used = result.pop("_backend_used", req.backend or "auto")
    return ChatResponse(
        **result,
        usage=Usage(backend=backend_used, duration_s=round(dur, 3)),
    )


@app.get("/healthz")
async def healthz():
    """Simple liveness — always 200 if process is up."""
    return {"status": "alive"}


@app.get("/readyz")
async def readyz():
    """Readiness — only 200 if at least one CLI is available."""
    cl = await claude_cli.is_available()
    ge = await gemini_cli.is_available()
    if not (cl or ge):
        raise HTTPException(status_code=503, detail="no CLI backend available")
    return {"status": "ready", "claude": cl, "gemini": ge}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=HTTP_PORT, reload=True)
