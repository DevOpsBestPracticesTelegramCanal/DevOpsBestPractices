# -*- coding: utf-8 -*-
"""
===============================================================================
QWENCODE FASTAPI SERVER - Async LLM Server
===============================================================================

Phase 3 Refactoring: Flask → FastAPI migration for async support.

Features:
- Async LLM calls (non-blocking)
- Server-Sent Events (SSE) streaming
- Concurrent request handling
- Same API as Flask server (backwards compatible)

Usage:
    # Start server
    python qwencode_fastapi.py

    # Or with uvicorn directly
    uvicorn qwencode_fastapi:app --host 0.0.0.0 --port 5000 --reload

Endpoints:
    GET  /                    - Web UI
    GET  /health              - Health check
    POST /api/chat            - Main chat endpoint (SSE)
    POST /api/execute         - Direct tool execution
    GET  /api/stats           - Server statistics
    GET  /api/models          - List models
    POST /api/config          - Update configuration

===============================================================================
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, AsyncGenerator
import aiohttp

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# UNIFIED IMPORTS
from core.unified_tools import UnifiedTools, get_tools
from core.pattern_router import PatternRouter, get_router

# SWECAS classifier
try:
    from core.swecas_classifier import SWECASClassifier
    swecas_classifier = SWECASClassifier()
    HAS_SWECAS = True
except ImportError:
    swecas_classifier = None
    HAS_SWECAS = False

# LLM Provider
try:
    from core.llm import get_provider, GenerationParams, LLMConfig, OllamaProvider
    HAS_LLM_PROVIDER = True
except ImportError:
    HAS_LLM_PROVIDER = False

# Observability (Phase 4)
try:
    from core.observability import (
        get_logger, configure_logging, LogLevel,
        metrics, trace, get_trace_id
    )
    HAS_OBSERVABILITY = True
    configure_logging(level=LogLevel.INFO, json_output=False)
    logger = get_logger("qwencode.fastapi")
except ImportError:
    HAS_OBSERVABILITY = False
    logger = None

# ApprovalManager
try:
    from core.approval_manager import (
        ApprovalManager, ApprovalRequest, ApprovalChoice,
        RiskLevel, RiskAssessor, get_approval_manager
    )
    HAS_APPROVAL = True
except ImportError:
    HAS_APPROVAL = False


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class ServerConfig:
    """Server configuration"""
    ollama_url: str = "http://localhost:11434"
    fast_model: str = "qwen2.5-coder:3b"
    heavy_model: str = "qwen2.5-coder:7b"
    max_tokens_fast: int = 400
    max_tokens_deep: int = 800
    ollama_timeout: int = 120
    project_root: str = str(Path(__file__).parent)


config = ServerConfig()

# Statistics
stats = {
    "requests_total": 0,
    "requests_fast_path": 0,
    "requests_deep_path": 0,
    "errors": 0,
    "start_time": datetime.now().isoformat()
}


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str
    mode: str = "auto"  # auto, fast, deep, search
    model: Optional[str] = None


class ExecuteRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


class ConfigUpdate(BaseModel):
    fast_model: Optional[str] = None
    heavy_model: Optional[str] = None
    ollama_url: Optional[str] = None
    max_tokens_fast: Optional[int] = None
    max_tokens_deep: Optional[int] = None


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="QwenCode Server",
    description="Async LLM-powered code assistant",
    version="2.2.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Observability Middleware
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Add tracing and metrics to all requests"""
    start_time = time.perf_counter()

    # Generate or extract trace ID
    trace_id = request.headers.get("X-Trace-ID", None)

    # Log and trace if observability is available
    if HAS_OBSERVABILITY:
        with trace(f"{request.method} {request.url.path}", trace_id=trace_id) as span:
            span.set_attribute("method", request.method)
            span.set_attribute("path", request.url.path)
            span.set_attribute("client", request.client.host if request.client else "unknown")

            response = await call_next(request)

            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("status_code", response.status_code)
            span.set_attribute("duration_ms", round(duration_ms, 2))

            # Metrics
            metrics.counter("http_requests_total", labels={"method": request.method, "path": request.url.path}).inc()
            metrics.histogram("http_request_duration_seconds").observe(duration_ms / 1000)

            if response.status_code >= 400:
                metrics.counter("http_errors_total", labels={"status": str(response.status_code)}).inc()

            # Add trace ID to response headers
            response.headers["X-Trace-ID"] = span.trace_id

            return response
    else:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        return response


# Templates
templates_dir = Path(__file__).parent / "templates"
if templates_dir.exists():
    templates = Jinja2Templates(directory=str(templates_dir))
else:
    templates = None

# Static files (Phase 5: Modular Frontend)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Initialize tools and router
tools = get_tools(config.project_root)
router = get_router()


# ============================================================================
# SSE HELPERS
# ============================================================================

def sse_event(event_type: str, data: Dict) -> str:
    """Format SSE event"""
    data["event"] = event_type
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_status(text: str) -> str:
    return sse_event("status", {"text": text})


def sse_response(text: str, source: str = "llm") -> str:
    return sse_event("response", {"text": text, "source": source})


def sse_tool(name: str, params: Dict) -> str:
    return sse_event("tool", {"name": name, "params": params})


def sse_done(success: bool = True, path: str = "fast", **extra) -> str:
    return sse_event("done", {"success": success, "path": path, **extra})


def sse_error(message: str) -> str:
    return sse_event("error", {"message": message})


# ============================================================================
# ASYNC LLM CLIENT
# ============================================================================

class AsyncLLMClient:
    """Async HTTP client for LLM calls using aiohttp"""

    def __init__(self, base_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def generate(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 400,
        temperature: float = 0.1
    ) -> str:
        """Async text generation"""
        session = await self._get_session()

        try:
            async with session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature
                    }
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "")
                else:
                    return f"LLM Error: HTTP {response.status}"

        except asyncio.TimeoutError:
            return "LLM Error: Timeout"
        except aiohttp.ClientConnectorError:
            return "LLM Error: Ollama not running"
        except Exception as e:
            return f"LLM Error: {e}"

    async def stream(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 400,
        temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        """Async streaming generation"""
        session = await self._get_session()

        try:
            async with session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature
                    }
                }
            ) as response:
                async for line in response.content:
                    if line:
                        try:
                            data = json.loads(line.decode('utf-8'))
                            chunk = data.get("response", "")
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            yield f"[Error: {e}]"

    async def is_available(self) -> bool:
        """Check if Ollama is running"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/tags") as response:
                return response.status == 200
        except:
            return False

    async def list_models(self) -> List[str]:
        """List available models"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/tags") as response:
                if response.status == 200:
                    data = await response.json()
                    return [m["name"] for m in data.get("models", [])]
        except:
            pass
        return []

    async def close(self):
        """Close the session"""
        if self._session and not self._session.closed:
            await self._session.close()


# Global async LLM client
llm_client = AsyncLLMClient(config.ollama_url, config.ollama_timeout)


# ============================================================================
# TOOL EXECUTION
# ============================================================================

def format_tool_result(tool: str, result: Any) -> str:
    """Format tool result for display"""
    if isinstance(result, dict):
        if "error" in result:
            return f"**Error:** {result['error']}"
        if "content" in result:
            content = result["content"]
            if len(content) > 2000:
                return f"```\n{content[:2000]}...\n```\n*(truncated)*"
            return f"```\n{content}\n```"
        return json.dumps(result, indent=2, ensure_ascii=False)

    if isinstance(result, list):
        if len(result) > 20:
            return "\n".join(f"- {item}" for item in result[:20]) + f"\n... +{len(result)-20} more"
        return "\n".join(f"- {item}" for item in result)

    return str(result)


async def execute_tool_async(tool: str, params: Dict) -> Any:
    """Execute tool (sync tools run in thread pool)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: tools.execute(tool, params))


# ============================================================================
# ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve web UI"""
    if templates:
        return templates.TemplateResponse("qwencode_terminal.html", {"request": request})
    return HTMLResponse("<h1>QwenCode Server</h1><p>Templates not found</p>")


@app.get("/health")
async def health():
    """Health check"""
    ollama_ok = await llm_client.is_available()
    uptime = (datetime.now() - datetime.fromisoformat(stats["start_time"])).total_seconds()

    # Update metrics if available
    if HAS_OBSERVABILITY:
        metrics.gauge("server_uptime_seconds").set(uptime)

    return {
        "status": "healthy" if ollama_ok else "degraded",
        "ollama": ollama_ok,
        "swecas": HAS_SWECAS,
        "approval": HAS_APPROVAL,
        "llm_provider": HAS_LLM_PROVIDER,
        "observability": HAS_OBSERVABILITY,
        "uptime_seconds": uptime
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Main chat endpoint with SSE streaming"""

    async def generate_response() -> AsyncGenerator[str, None]:
        global stats
        stats["requests_total"] += 1
        message = request.message.strip()

        try:
            yield sse_status("Processing...")

            # 1. Try Pattern Router (Fast Path)
            route = router.match(message)

            if route:
                yield sse_status(f"Fast Path: {route['tool']}")
                yield sse_tool(route["tool"], route["params"])

                # Execute tool
                result = await execute_tool_async(route["tool"], route["params"])
                formatted = format_tool_result(route["tool"], result)

                yield sse_response(f"## {route['tool'].upper()}\n\n{formatted}", "pattern")
                stats["requests_fast_path"] += 1
                yield sse_done(True, "fast")
                return

            # 2. Deep Path (LLM)
            yield sse_status(f"Deep Path: {config.fast_model}")

            # SWECAS classification
            swecas_info = None
            if HAS_SWECAS and swecas_classifier:
                try:
                    classification = swecas_classifier.classify(message)
                    swecas_info = {
                        "category": classification.category.value if hasattr(classification, 'category') else str(classification),
                        "confidence": getattr(classification, 'confidence', 0.8)
                    }
                    yield sse_status(f"SWECAS: {swecas_info['category']}")
                except:
                    pass

            # Stream LLM response
            full_response = ""
            async for chunk in llm_client.stream(
                message,
                config.fast_model,
                config.max_tokens_deep
            ):
                full_response += chunk
                yield sse_response(chunk, "llm")

            stats["requests_deep_path"] += 1
            yield sse_done(True, "deep", swecas=swecas_info)

        except Exception as e:
            stats["errors"] += 1
            yield sse_error(str(e))
            yield sse_done(False, "error")

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/execute")
async def execute(request: ExecuteRequest):
    """Direct tool execution"""
    try:
        result = await execute_tool_async(request.tool, request.params)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Get server statistics"""
    uptime = (datetime.now() - datetime.fromisoformat(stats["start_time"])).total_seconds()
    return {
        **stats,
        "uptime_seconds": uptime,
        "config": {
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "ollama_url": config.ollama_url
        },
        "features": {
            "swecas": HAS_SWECAS,
            "approval": HAS_APPROVAL,
            "llm_provider": HAS_LLM_PROVIDER
        }
    }


@app.get("/api/models")
async def list_models():
    """List available models"""
    models = await llm_client.list_models()
    return {
        "success": True,
        "models": [{"name": m, "provider": "ollama"} for m in models],
        "current_fast": config.fast_model,
        "current_heavy": config.heavy_model
    }


@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Update server configuration"""
    if update.fast_model:
        config.fast_model = update.fast_model
    if update.heavy_model:
        config.heavy_model = update.heavy_model
    if update.ollama_url:
        config.ollama_url = update.ollama_url
        # Recreate LLM client with new URL
        global llm_client
        await llm_client.close()
        llm_client = AsyncLLMClient(config.ollama_url, config.ollama_timeout)
    if update.max_tokens_fast:
        config.max_tokens_fast = update.max_tokens_fast
    if update.max_tokens_deep:
        config.max_tokens_deep = update.max_tokens_deep

    return {
        "success": True,
        "config": {
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "ollama_url": config.ollama_url,
            "max_tokens_fast": config.max_tokens_fast,
            "max_tokens_deep": config.max_tokens_deep
        }
    }


@app.get("/api/mode")
async def get_mode():
    """Get current execution mode"""
    return {
        "mode": "auto",
        "available": ["auto", "fast", "deep", "search"],
        "description": {
            "auto": "Automatic mode selection",
            "fast": "Fast path only (PatternRouter)",
            "deep": "Deep path (LLM + SWECAS)",
            "search": "Deep + web search"
        }
    }


@app.get("/api/debug/route")
async def debug_route(message: str):
    """Debug routing for a message"""
    result = router.match(message)
    return {
        "input": message,
        "route": result,
        "would_use": "fast_path" if result else "deep_path"
    }


# ============================================================================
# OBSERVABILITY ENDPOINTS (Phase 4)
# ============================================================================

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    if HAS_OBSERVABILITY:
        return JSONResponse(
            content=metrics.to_dict(),
            media_type="application/json"
        )
    return {"error": "Observability not available"}


@app.get("/metrics/prometheus")
async def get_prometheus_metrics():
    """Prometheus text format metrics"""
    if HAS_OBSERVABILITY:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=metrics.to_prometheus(),
            media_type="text/plain"
        )
    return PlainTextResponse(content="# Observability not available", media_type="text/plain")


@app.get("/api/traces")
async def get_traces(limit: int = 50):
    """Get recent traces for debugging"""
    if HAS_OBSERVABILITY:
        from core.observability import get_recent_traces
        return {"traces": get_recent_traces(limit)}
    return {"error": "Observability not available", "traces": []}


# ============================================================================
# WEBSOCKET ENDPOINT (Real-time streaming)
# ============================================================================

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat streaming.

    Message format (client -> server):
        {"message": "user input", "model": "optional model name"}

    Message format (server -> client):
        {"type": "status", "data": "Processing..."}
        {"type": "chunk", "data": "token"}
        {"type": "done", "data": {"success": true}}
        {"type": "error", "data": "error message"}
    """
    await websocket.accept()

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message", "")
            model = data.get("model", config.fast_model)

            if not message:
                await websocket.send_json({
                    "type": "error",
                    "data": "Empty message"
                })
                continue

            stats["requests_total"] += 1

            # Status update
            await websocket.send_json({
                "type": "status",
                "data": f"Processing with {model}..."
            })

            # Check fast path
            route = router.match(message)
            if route:
                stats["requests_fast_path"] += 1
                await websocket.send_json({
                    "type": "chunk",
                    "data": route
                })
                await websocket.send_json({
                    "type": "done",
                    "data": {"success": True, "path": "fast"}
                })
                continue

            # Deep path - stream response
            stats["requests_deep_path"] += 1
            try:
                async for chunk in llm_client.stream(message, model, config.max_tokens_deep):
                    await websocket.send_json({
                        "type": "chunk",
                        "data": chunk
                    })

                await websocket.send_json({
                    "type": "done",
                    "data": {"success": True, "path": "deep"}
                })
            except Exception as e:
                stats["errors"] += 1
                await websocket.send_json({
                    "type": "error",
                    "data": str(e)
                })

    except WebSocketDisconnect:
        pass  # Client disconnected normally
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": f"WebSocket error: {e}"
            })
        except:
            pass


# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    """Startup tasks"""
    # Use logger if available
    if HAS_OBSERVABILITY:
        logger.info("Server starting", version="2.2.0")

    print("=" * 60)
    print("  QWENCODE FASTAPI SERVER v2.2.0")
    print("=" * 60)
    print(f"  Ollama URL:     {config.ollama_url}")
    print(f"  Fast Model:     {config.fast_model}")
    print(f"  Heavy Model:    {config.heavy_model}")
    print(f"  SWECAS:         {HAS_SWECAS}")
    print(f"  Approval:       {HAS_APPROVAL}")
    print(f"  LLM Provider:   {HAS_LLM_PROVIDER}")
    print(f"  Observability:  {HAS_OBSERVABILITY}")
    print("=" * 60)

    # Check Ollama
    if await llm_client.is_available():
        print("  [OK] Ollama is running")
        models = await llm_client.list_models()
        print(f"  [OK] Models available: {len(models)}")
        if HAS_OBSERVABILITY:
            metrics.gauge("ollama_available").set(1)
            metrics.gauge("ollama_models_count").set(len(models))
    else:
        print("  [WARN] Ollama not running!")
        if HAS_OBSERVABILITY:
            metrics.gauge("ollama_available").set(0)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    await llm_client.close()
    print("Server shutdown complete")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "qwencode_fastapi:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info"
    )
