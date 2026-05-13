"""FastAPI front-end for the participant-side OpenRouter proxy.

The server exposes a single ``/v1/chat/completions`` endpoint with an
OpenAI-compatible shape so that participant harnesses can point their
existing OpenAI / OpenRouter SDKs at the proxy without code changes.

Every request is validated by :mod:`proxy.policy` first and forwarded
upstream only when it passes. All requests, responses and policy
violations are appended to a JSONL audit log.

Run locally::

    uvicorn proxy.main:app --host 0.0.0.0 --port 8080

This is the development entrypoint; production deployments should also
run inside the same docker network as the sandbox runner with strict
egress rules (only :data:`OPENROUTER_BASE` allowed).
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from proxy.audit_log import AuditLog, AuditRecord, hash_prompt
from proxy.client import OPENROUTER_BASE, OpenRouterError, _parse_completion
from proxy.policy import PolicyViolation, enforce_request

app = FastAPI(title="wanghong-leaderboard proxy", version="0.0.1")

_AUDIT = AuditLog(os.environ.get("PROXY_AUDIT_DIR", "./proxy/audit_logs"))


def _upstream_key() -> str:
    key = os.environ.get("OPENROUTER_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="OPENROUTER_KEY is not configured")
    return key


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "audit_log": str(_AUDIT.path)}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    x_run_id: str | None = Header(default=None, alias="X-Run-Id"),
    x_harness_digest: str | None = Header(default=None, alias="X-Harness-Digest"),
) -> JSONResponse:
    body = await request.json()
    request_id = str(uuid.uuid4())
    run_id = x_run_id or "unbound"
    prompt_hash = hash_prompt(body.get("messages") or []) if isinstance(body, dict) else None

    try:
        decision = enforce_request(body)
    except PolicyViolation as exc:
        _AUDIT.write(
            AuditRecord(
                request_id=request_id,
                run_id=run_id,
                harness_digest=x_harness_digest,
                direction="violation",
                model=(body or {}).get("model") if isinstance(body, dict) else None,
                prompt_sha256=prompt_hash,
                violation=str(exc),
            )
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _AUDIT.write(
        AuditRecord(
            request_id=request_id,
            run_id=run_id,
            harness_digest=x_harness_digest,
            direction="request",
            model=decision.request.get("model"),
            prompt_sha256=prompt_hash,
        )
    )

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as http:
            upstream = await http.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {_upstream_key()}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/dirtycomputer/wanghong_leaderboard",
                    "X-Title": "wanghong-leaderboard",
                },
                json=decision.request,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        payload = upstream.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="upstream returned non-JSON") from exc

    if upstream.status_code >= 400:
        _AUDIT.write(
            AuditRecord(
                request_id=request_id,
                run_id=run_id,
                harness_digest=x_harness_digest,
                direction="response",
                model=decision.request.get("model"),
                prompt_sha256=prompt_hash,
                latency_ms=latency_ms,
                violation=f"upstream_status_{upstream.status_code}",
                extra={"upstream_payload": payload},
            )
        )
        return JSONResponse(status_code=upstream.status_code, content=payload)

    completion = _parse_completion(payload)
    _AUDIT.write(
        AuditRecord(
            request_id=request_id,
            run_id=run_id,
            harness_digest=x_harness_digest,
            direction="response",
            model=completion.model or decision.request.get("model"),
            provider=completion.provider,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            total_tokens=(completion.input_tokens or 0) + (completion.output_tokens or 0)
            if completion.input_tokens is not None and completion.output_tokens is not None
            else None,
            finish_reason=completion.finish_reason,
            latency_ms=latency_ms,
            prompt_sha256=prompt_hash,
        )
    )
    return JSONResponse(status_code=200, content=payload)


__all__ = ["app", "OpenRouterError"]
